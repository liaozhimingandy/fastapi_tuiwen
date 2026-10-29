"""FastAPI 依赖注入中心(Composition Root)。

职责分三段:
1. 认证依赖: OAuth2 Bearer 令牌解析(check_authentication / get_current_user /
   get_current_active_user), 校验通过后把 account_id / salt 写入 request.state;
2. 会话依赖: 请求级数据库会话(get_session / get_conn);
3. DI 工厂: 为每张表提供「写会话+读会话 → DAO → Service」的依赖链,
   api 层统一通过 get_xxx_service(...) 注入, Service 再通过 dao 访问数据。

约定: DAO 只 flush 不 commit, 事务提交/回滚出口统一在 API 层(dao.commit()/rollback())。
"""
import uuid
from typing import Annotated, AsyncGenerator, Any
from sqlmodel import select
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

# 公开路由(免登录)用: auto_error=False 让"没带令牌"时参数为 None 而不是 401
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/oauth/authorize/password/", auto_error=False)


async def get_optional_account_id(
        token: Annotated[str | None, Depends(oauth2_scheme_optional)],
) -> uuid.UUID | None:
    """可选认证: 带合法令牌就返回账户ID, 没带或非法一律返回 None。

    用于「允许匿名、但登录后要记录归属」的公开接口(如视频上传)。
    这些路由挂在无认证依赖的 router_public 上, request.state 里不会有 account_id ——
    原实现直接用 request.state.account_id, 结果上传者永远是 None, 作者信息丢失。

    NOTE: 令牌非法时静默降级为匿名, 不抛 401 —— 公开接口不应因一个坏令牌而不可用。
    """
    if not token:
        return None
    payload = verify_jwt_token(token, grant_type="access_token")
    if "message" in payload:
        return None
    try:
        return uuid.UUID(str(payload["account_id"]))
    except (KeyError, TypeError, ValueError):
        return None

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
                      '/accounts/password/reset/']  # 排除的路径(免登录白名单)

    # 实际 request.url.path 带 /api/v2 总前缀, 去掉后再比对白名单
    api_prefix = "/api/v2"
    path = request.url.path
    norm_path = path[len(api_prefix):] if path.startswith(api_prefix) else path
    if path in excluded_paths or norm_path in excluded_paths:
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

    # NOTE: 令牌里缺 account_id / salt 时会抛 KeyError(500) 而非 401;
    #       若存在历史令牌或签发逻辑变更, 建议改用 payload.get() 并统一返回 401。
    # 令牌载荷里是 UUID 字符串, 这里统一转成 UUID 对象:
    # 下游与主键列比较、拼 Redis key 都不必再做类型转换
    try:
        request.state.account_id = uuid.UUID(str(payload["account_id"]))
    except (KeyError, ValueError, TypeError):
        raise credentials_exception
    request.state.salt = payload.get("salt")


async def get_current_user(
        security_scopes: SecurityScopes,
        token: Annotated[str, Depends(oauth2_scheme)],
        session: Annotated[AsyncSession, "请求级只读会话, 用于回库确认账户"] = Depends(get_read_session),
) -> Account:
    """
        在需要用户信息的地方调用

        校验顺序: 令牌签名/有效期/类型 → scope 权限 → 回库取真实账户。
        令牌里只有 account_id 与 salt, 账户资料与状态一律以库中数据为准:
        账户不存在(已注销)时直接 401, 避免返回只带 account_id 的占位对象。

        Args:
            security_scopes: 权限范围,可以为空
            token: 令牌,从Header中获取
            session: 请求级只读会话; 认证只做一次唯一索引查询, 无需写会话

        Returns:
            Account: 数据库中的账户实例(字段为真实值, 非仅 account_id 的占位对象)

        Raises:
            HTTPException: 401 —— 令牌无效/过期/类型不符、scope 不足、账户不存在

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

    # 先做纯令牌侧的 scope 校验: 权限不足无需白跑一次数据库
    token_scopes = payload.get("scopes", [])
    for scope in security_scopes.scopes:
        if scope not in token_scopes:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not enough permissions",
                headers={"WWW-Authenticate": authenticate_value},
            )

    # 回库取真实账户: account_id 上是唯一索引, 这次查询走索引且只读, 代价很小
    # (认证属框架级原语, 直接查表而不经 Service/DAO, 避免为一次主键查询再开一个写会话)
    result = await session.exec(select(Account).where(Account.id == payload["account_id"]))
    instance = result.first()
    if not instance:
        # 令牌签名有效但账户已被删除/注销, 与令牌无效同样处理, 不泄露账户是否存在
        raise credentials_exception

    return instance


async def get_current_active_user(
        current_user: Account = Security(get_current_user, scopes=["admin"]),
) -> Account:
    """在 get_current_user 基础上再校验账户是否被禁用。

    get_current_user 现已回库取真实账户, 因此这里的 is_active 是库中的真实状态,
    不再恒为模型默认值 True —— is_active=False 的账号会被真正拦下。

    NOTE: 该字段声明为 bool | None(可空), 判据用 `not` 会让 NULL 也视为未激活而被拦截;
          若线上存在 is_active 为 NULL 的历史数据, 需先刷成 True 再启用本依赖。
    NOTE: 目前没有任何路由引用它, 需要拦截禁用账号时在对应接口上用它替换 get_current_user。
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
            headers={"WWW-Authenticate": "Bearer"},
        )
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


async def get_conn(request: Request) -> AsyncGenerator[Any, Any]:
    """返回 asyncpg 原生连接(需先由 lifespan 把连接池挂到 app.state.pool), 适合批量/COPY 场景。

    注意: 连接池对象要从 request.app.state 取, 而不是声明 app: FastAPI 参数 ——
          依赖函数的参数会被 FastAPI 当作请求参数(Query/Body)解析, 直接注入 app 会报错。
          当前 main.py 里 app.state.pool 的赋值仍处于注释状态, 启用前需先在 lifespan 挂上。
    """
    async with request.app.state.pool.acquire() as conn:
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

async def get_favorite_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.favorite import FavoriteDAO
    return FavoriteDAO(
        write_db=write_db,
        read_db=read_db,
    )

def get_favorite_service(dao = Depends(get_favorite_dao)):
    from src.tuiwen.service.favorite import FavoriteService
    return FavoriteService(dao=dao)

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

async def get_video_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.video import VideoDAO
    return VideoDAO(
        write_db=write_db,
        read_db=read_db,
    )

async def get_video_source_dao(
    write_db: AsyncSession = Depends(get_write_session),
    read_db: AsyncSession = Depends(get_read_session),
):
    from src.tuiwen.dal.video_source import VideoSourceDAO
    return VideoSourceDAO(
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

def get_follow_service(dao = Depends(get_follow_dao), like_dao = Depends(get_like_dao)):
    from src.tuiwen.service.follow import FollowService
    # like_dao 只用于统计「获赞数」, 点赞数据不在关注表里
    return FollowService(dao=dao, like_dao=like_dao)

def get_account_service(dao = Depends(get_account_dao)):
    from src.tuiwen.service.account import AccountService
    return AccountService(dao=dao)

def get_feedback_service(dao = Depends(get_feedback_dao)):
    from src.tuiwen.service.feedback import FeedbackService
    return FeedbackService(dao=dao)

def get_video_service(dao = Depends(get_video_dao), source_dao=Depends(get_video_source_dao)):
    from src.tuiwen.service.video import VideoService
    return VideoService(dao=dao, source_dao=source_dao)