"""FastAPI 依赖注入中心(Composition Root)。

职责分三段:
1. 认证依赖: OAuth2 Bearer 令牌解析(check_authentication / get_current_user /
   get_current_active_user), 校验通过后把 account_id / salt 写入 request.state;
2. 会话依赖: 请求级数据库会话(get_session / get_conn);
3. DI 工厂: 为每张表提供「写会话+读会话 → DAO → Service」的依赖链,
   api 层统一通过 get_xxx_service(...) 注入, Service 再通过 dao 访问数据。

约定: DAO 只 flush 不 commit, 事务提交/回滚出口统一在 API 层(dao.commit()/rollback())。
"""
from typing import Annotated, AsyncGenerator, Any
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import Depends, HTTPException, Security, Request, FastAPI, status
from fastapi.security import SecurityScopes, OAuth2PasswordBearer

from src.tuiwen.core import AsyncSessionLocal
from src.tuiwen.utils import verify_jwt_token
# Account 模型随模块重构已迁移到 model 包(src.tuiwen.account 不存在),
# 这里同步修正导入路径, 否则本模块(及整个应用) import 即失败
from src.tuiwen.model.account import Account

from src.tuiwen.core.database import (
    get_write_session,
    get_read_session,
)


# OAuth2 密码流: 文档页的 Authorize 按钮会把 token 请求发到该地址
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/oauth/authorize/password/", scopes={
    "basic": "basic access",
    "admin": "write access and read access"
})

async def check_authentication(request: Request, token: Annotated[str, Depends(oauth2_scheme)]):
    """
    检查令牌是否有效

    Args:
        request: 请求对象
        token: 令牌

    Returns:
        令牌信息
    Example usage:
        @router_oauth.get("/test-oauth/", summary="测试接口(基础权限)")
    """
    excluded_paths = ["/docs",
                      "/openapi.json",
                      '/redoc',
                      '/oauth/authorize/password/',
                      '/accounts/password/reset/',
                      '/oauth/authorize/password/']  # 排除的路径(免登录白名单; 列表内有重复项, 可清理)

    if request.url.path in excluded_paths:
        return None  # 如果是排除路径，不做认证检查

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='invalid authentication credentials',
        headers={'WWW-Authenticate': 'Bearer'}
    )

    try:
        payload = verify_jwt_token(token, grant_type='access_token' if not request.url.path.startswith('/oauth/refresh-token/') else 'refresh_token')
        assert 'message' not in payload, payload["message"]
    except AssertionError as e:
        credentials_exception.detail = str(e)
        raise credentials_exception

    request.state.account_id = payload["account_id"]
    request.state.salt = payload["salt"]


async def get_current_user(security_scopes: SecurityScopes, token: Annotated[str, Depends(oauth2_scheme)]):
    """
        在需要用户信息的地方调用

        Args:
            security_scopes: 权限范围,可以为空
            token: 令牌,从Header中获取

        Returns:
            用户信息

        Example usage:

            @router_oauth.get("/test-oauth/", summary="测试接口(基础权限)")
            def test_oauth(user: Account = Depends(get_current_user)) -> Any:
                return {"message": f"hello word, 欢迎您,{user.account_id}"}

            @router_oauth.get("/test-oauth-admin/", summary="测试接口(需要更高权限)")
            def test_oauth(user: Account = Security(get_current_user, scopes=['admin'])) -> Any:
                return {"message": f"hello word, 欢迎您,{user.account_id}"}

    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'}
    )
    if security_scopes.scopes:
        authenticate_value = f'Bearer scope="{security_scopes.scope_str}"'
    else:
        authenticate_value = "Bearer"

    try:
        payload = verify_jwt_token(token, grant_type='access_token')
        assert 'message' not in payload, payload["message"]
    except AssertionError:
        raise credentials_exception

    token_scopes = payload.get("scopes", [])
    instance = Account(account_id=payload["account_id"])
    # #  数据库查询用户信息
    # statement = select(Account).where(Account.account_id == payload["account_id"])
    # results = await session.exec(statement)
    # instance = results.first()
    # if not instance:
    #     raise credentials_exception

    for scope in security_scopes.scopes:
        if scope not in token_scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )

    return instance


async def get_current_active_user(
        current_user: Account = Security(get_current_user, scopes=["admin"]),
):
    """在 get_current_user 基础上再校验账户是否被禁用(is_active=False 直接 401)。

    NOTE: 这里用的 Account 只带了 account_id, 未查库, is_active 取的是模型默认值 True,
          实际不会拦截被禁用的账号; 需要真正拦截时应补一次数据库查询
    """
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not enough permissions")
    return current_user


# ========== 会话依赖（供路由层使用） ==========
async def get_session() -> AsyncGenerator[Any, Any]:
    """标准异步会话依赖(经 AsyncSessionLocal 工厂构造), 异常自动回滚、请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_conn(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """返回 asyncpg 原生连接(需先由 lifespan 把连接池挂到 app.state.pool), 适合批量/COPY 场景。"""
    async with app.state.pool.acquire() as conn:
        yield conn


# ========== DAO 依赖工厂(每张表一个: 写会话 + 读会话 → DAO 实例) ==========
async def get_notice_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.notice import NoticeDAO
    return NoticeDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_feedback_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.feedback import FeedbackDAO
    return FeedbackDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_snap_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.snap import SnapDAO
    return SnapDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_like_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.like import LikeDAO
    return LikeDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_post_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.post import PostDAO
    return PostDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_comment_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.comment import CommentDAO
    return CommentDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_upload_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.file import FileDAO
    return FileDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_follow_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.follow import FollowDAO
    return FollowDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_account_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.account import AccountDAO
    return AccountDAO(
        write_db=write_db,
        read_db=read_db,
    )


# ========== Service 依赖工厂(DAO → Service; api 层实际注入的就是这些) ==========
def get_notice_service(dao = Depends(get_notice_dao)):
    from src.tuiwen.service.notice import NoticeService
    return NoticeService(dao=dao)

def get_snap_service(dao = Depends(get_snap_dao)):
    from src.tuiwen.service.snap import SnapService
    return SnapService(dao=dao)

def get_like_service(dao = Depends(get_like_dao)):
    from src.tuiwen.service.like import LikeService
    return LikeService(dao=dao)

def get_post_service(dao = Depends(get_post_dao)):
    from src.tuiwen.service.post import PostService
    return PostService(dao=dao)

def get_comment_service(dao = Depends(get_comment_dao)):
    from src.tuiwen.service.comment import CommentService
    return CommentService(dao=dao)


def get_upload_service(dao = Depends(get_upload_dao)):
    from src.tuiwen.service.file import FileService
    return FileService(dao=dao)

def get_follow_service(dao = Depends(get_follow_dao)):
    from src.tuiwen.service.follow import FollowService
    return FollowService(dao=dao)

def get_account_service(dao = Depends(get_account_dao)):
    from src.tuiwen.service.account import AccountService
    return AccountService(dao=dao)

def get_feedback_service(dao = Depends(get_feedback_dao)):
    from src.tuiwen.service.feedback import FeedbackService
    return FeedbackService(dao=dao)