from typing import Annotated

from fastapi import Depends, HTTPException, Security, Request, FastAPI
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from src.tuiwen.account.models import Account
from src.tuiwen.core.database import AsyncSessionLocal
from src.tuiwen.utils.jwt_token import verify_jwt_token

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
                      '/oauth/authorize/password/']  # 排除的路径

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
    except AssertionError as _:
        raise credentials_exception

    request.state.account_id = payload["account_id"]


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
    """用于进一步过滤是否有数据操作权限的用户信息"""
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not enough permissions")
    return current_user


# 获取异步session的依赖
async def get_session() -> AsyncSession:
    """获取数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session


async def get_conn(app: FastAPI) -> AsyncSession:
    """返回数据库会话;适合手动管理连接"""
    async with app.state.pool.acquire() as conn:
        yield conn
