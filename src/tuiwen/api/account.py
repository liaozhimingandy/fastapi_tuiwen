"""
账号 / 认证 API 路由层

职责:
    1. 注册、登录换令牌、刷新令牌、找回/修改密码、用户名查重、认证信息变更
    2. 人机检测(Cloudflare Turnstile)校验
    3. 健康检查与根路径重定向

路由分组:
    router_public  : 免登录接口(注册/登录/验证码/重置密码/健康检查)
    router_oauth   : 需登录的令牌相关接口(刷新令牌、鉴权自测)
    router_account : 需登录的账号资料类接口, 统一前缀 /accounts

分层位置:
    API → AccountService → AccountDAO → PostgreSQL (+ Redis 验证码 + SMTP 邮件)

异常约定:
    Service 层抛 BizError(业务异常), API 层统一转换为 HTTPException。
"""
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, status, Depends, Request, Query, HTTPException, BackgroundTasks, Security
from fastapi.security import OAuth2PasswordRequestForm
from starlette.responses import RedirectResponse

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dependencies import get_account_service, get_current_user, oauth2_scheme
from src.tuiwen.service.account import AccountService
from src.tuiwen.model.oauth import RefreshToken, AccessToken, CodeVerify, TurnstileVerifyToken, UpdateCredential
from src.tuiwen.model.account import AccountInfo, AccountCreate, Account, AccountPublicCommon, AccountPasswordChange, \
    AccountPasswordReset, AccountPublic
from src.tuiwen.core import Tag
from src.tuiwen.models import PageResponse
from src.tuiwen.utils.mail_service import send_reset_pwd_mail
from src.tuiwen.utils.utils import convert_to_cst_time

router_account = APIRouter(tags=[Tag.oauth])
# 免登录路由: 各接口自己带了完整路径(如 /accounts/register/), 因此这里不能给 prefix='/'
# —— FastAPI 会断言「prefix 不能以 / 结尾」, 直接 import 就报错
router_public = APIRouter(tags=[Tag.account, ])

# =========================================================
# 认证 / 令牌
# =========================================================
@router_public.post("/oauth/authorize/password/",
                    summary="用户使用用户名或邮箱进和密码进行认证获取刷新令牌", tags=[Tag.oauth],
                    response_model=RefreshToken)
async def authorize(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                    svc: AccountService = Depends(get_account_service)):
    """
    用户进行认证获取刷新令牌 <br>

    Args:<br>
        username: 账户唯一标识,用户名或邮箱 <br>
        password: 账户密码 <br>
        session: 数据库操作会话依赖<br>

    Returns: <br>
        刷新token和一个请求token <br>

    """
    # 采用 OAuth2 标准密码模式, 入参由 OAuth2PasswordRequestForm 从表单解析
    try:
        return await svc.authorize(username=form_data.username, password=form_data.password)
    except BizError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router_public.get("/oauth/refresh-token/{account_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
                    tags=[Tag.oauth], response_model=AccessToken)
async def refresh_token(account_id: Annotated[str, "账户ID"],
                        token: Annotated[str, "刷新令牌"] = Depends(oauth2_scheme),
                        svc: AccountService = Depends(get_account_service)):
    """
    使用刷新令牌进行更新获取权限令牌,请使用postman测试,header携带认证信息,后续会实现,refresh_token有效期为7天,请妥善保管,重新登录认证后,
    该token作废; <br>

    Args: <br>
        account_id: 账户唯一标识 <br>
        refresh_token: 刷新token <br>

    Returns: <br>
        请求token <br>

    """
    # token 从 Authorization 头解析; 服务内部会校验其 grant_type 必须为 refresh_token
    try:
        return await svc.refresh_token(account_id=account_id, refresh_token=token)
    except BizError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router_account.get("/oauth/test-oauth/", summary="测试接口(基础权限)")
async def test_oauth(user: Annotated[Account, "账户信息"] = Depends(get_current_user)) -> Any:
    """连通性自测: 需要有效的 access_token(basic 权限)。"""
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


@router_account.get("/oauth/test-oauth-admin/", summary="测试接口(需要更高权限)")
async def test_oauth_admin(
        user: Annotated[Account, "认证的用户信息"] = Security(get_current_user, scopes=['admin'])) -> Any:
    """权限自测: 令牌中必须包含 admin scope, 否则返回 401。"""
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


# =========================================================
# 健康检查 / 根路径
# =========================================================
@router_public.get("/health-check/", tags=["health"], summary="服务检查检查")
async def health_check() -> dict[str, Any]:
    """服务存活探针, 返回固定 ok 与当前北京时间, 供 LB / K8s 探活使用。"""
    current_time = convert_to_cst_time(datetime.now())
    return {"message": "ok", "gmt_created": current_time}


@router_public.get("/", tags=["root"], summary="根路径", include_in_schema=False)
async def root(request: Annotated[Request, "请求对象"]) -> RedirectResponse:
    """根路径 301 永久重定向到健康检查接口。"""
    url_for_redirect = request.url_for("health_check")
    return RedirectResponse(url=url_for_redirect, status_code=301)


########################################################################################################################

# =========================================================
# 注册 / 查询
# =========================================================
@router_public.post("/accounts/register/", summary="用户注册", tags=[Tag.account],
                    response_model=AccountInfo, status_code=status.HTTP_201_CREATED)
async def register(account: Annotated[AccountCreate, Body(..., description="用户信息")],
                   svc: AccountService = Depends(get_account_service)):
    """
    新用户注册

    Args:
        account: 注册入参(邮箱/账号ID/密码等), 密码在 Service 层加盐哈希后存储
        svc: 账号业务服务

    Returns:
        AccountInfo: 对外可暴露的账号信息(不含密码与盐值)
    """
    try:
        return await svc.register(account)
    except BizError as e:
        # 业务异常回滚, 保证邮箱/用户名唯一性校验不会留下脏数据
        await svc.dao.write_db.rollback()
        # API层统一转HTTP异常
        raise HTTPException(
            status_code=e.code,
            detail=e.message
        )


@router_public.get("/accounts/{account_id}/", summary="查询账户信息",
                   response_model=AccountInfo,
                   name="get_account_public",
                   tags=[Tag.account, ],
                   responses={
                       404: {"description": "no such account"}
                   })
async def get_account(account_id: Annotated[str, "账户ID"],
                      svc: AccountService = Depends(get_account_service)) -> AccountPublic:
    """
    按账户ID查询公开的账号信息(免登录)

    Args:
        account_id: 账户唯一标识
        svc: 账号业务服务

    Returns:
        AccountPublic: 账号公开信息; 不存在时返回 404
    """
    instance = await svc.get_account(account_id)
    if not instance:
        raise HTTPException(status_code=404, detail="no such account")
    return instance


@router_account.put("/accounts/{account_id}/", summary="更新账户基本信息", response_model=AccountInfo, tags=[Tag.account])
async def update_account(account_id: Annotated[str, "账户ID"],
                         account: Annotated[AccountPublicCommon, Body(..., description="更新的账户信息")],
                         svc: AccountService = Depends(get_account_service),
                         user: Annotated[Account, "认证的用户信息"] = Depends(get_current_user)):
    """
    更新账户基本资料(昵称/头像等)

    敏感字段(account_id/username/mail/mobile/password/salt 等)在 Service 层被显式排除,
    且只允许操作自己的账户。

    Args:
        account_id: 目标账户ID
        account: 待更新的资料字段
        svc: 账号业务服务
        user: 当前登录用户, 用于越权校验

    Returns:
        AccountInfo: 更新后的账号信息
    """
    try:
        # 越权保护: 只允许修改自己的账户
        assert user.account_id == account_id, '请不要跨账户操作'
        return await svc.update_account(account_id, account)
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BizError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router_account.get("/accounts/search/{keyword}/", summary="通过关键词搜索账户", response_model=PageResponse[AccountPublic],
                    tags=[Tag.account])
async def search(keyword: Annotated[str, "关键词"], *, svc: AccountService = Depends(get_account_service),
                 offset: Annotated[int, "偏移量"] = 0,
                 limit: Annotated[int, Query(le=10)] = 10, ) -> PageResponse[AccountInfo]:
    """
    按关键词模糊搜索账户(昵称或账号ID包含关键词)

    Args:
        keyword: 搜索关键词, 内部会去空格并转小写
        svc: 账号业务服务
        offset: 偏移量
        limit: 每页数量, 最大 10

    Returns:
        PageResponse[AccountInfo]: 匹配到的账户列表与总数
    """
    dataset = await svc.search(keyword, offset, limit)
    return PageResponse(items=dataset, total=len(dataset), page_size=limit)


# =========================================================
# 密码找回 / 修改
# =========================================================
@router_public.post("/accounts/send/code/", summary="发送验证码", tags=[Tag.account])
async def account_send_code(data: Annotated[CodeVerify, "验证码信息"],
                            background_tasks: Annotated[BackgroundTasks, "后台任务"],
                            svc: AccountService = Depends(get_account_service)):
    """
    向指定邮箱发送重置密码验证码

    验证码写入 Redis(带过期时间)并做 1 小时发送限流;
    邮件通过 BackgroundTasks 异步发送, 不阻塞响应。

    Args:
        data: 接收验证码的邮箱信息
        background_tasks: 后台任务, 用于异步发信
        svc: 账号业务服务

    Returns:
        dict: 固定的提示文案, 不返回验证码本身
    """
    result = await svc.account_send_code(data)
    # 后台发送邮箱通知
    background_tasks.add_task(send_reset_pwd_mail, **result)
    return {"message": "验证码已经发送至你的邮箱,请查收!"}


@router_public.put("/accounts/password/reset/", summary="账号密码重置", tags=[Tag.account],
                   response_model=AccountInfo)
async def password_reset(account: Annotated[AccountPasswordReset, Body(..., description="密码重置的必要信息")],
                         svc: AccountService = Depends(get_account_service)):
    """
    忘记密码场景下的密码重置

    校验流程: 邮箱 → Redis 中的验证码 → 校验通过后立即删除验证码, 防止重复使用。

    Args:
        account: 重置入参(账号/验证码/新密码)
        svc: 账号业务服务

    Returns:
        AccountInfo: 重置后的账号信息
    """
    try:
        return await svc.reset_password(account)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router_account.put("/accounts/password/change/", summary="账号密码修改", response_model=AccountInfo,
                    status_code=status.HTTP_200_OK, tags=[Tag.account])
async def password_change(request: Annotated[Request, "请求对象"],
                          account: Annotated[AccountPasswordChange, Body(..., description="修改密码的必要入参")],
                          svc: AccountService = Depends(get_account_service)):
    """
    已登录状态下修改密码

    salt 取自令牌载荷(request.state.salt), 用于校验原密码哈希。

    Args:
        request: 请求对象, 携带 account_id 与 salt
        account: 修改入参(原密码 + 新密码)
        svc: 账号业务服务

    Returns:
        AccountInfo: 更新后的账号信息
    """
    try:
        return await svc.change_password(account_id=request.state.account_id, salt=request.state.salt, account=account)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =========================================================
# 人机检测 / 用户名 / 认证信息
# =========================================================
# 人机检测
@router_public.post('/auth/two_step_verification/', summary="人机检测校验接口", tags=[Tag.oauth], )
async def two_step_verification(data: Annotated[TurnstileVerifyToken, Body(..., description="人机检测校验接口")],
                                svc: AccountService = Depends(get_account_service)):
    """
    校验前端 Cloudflare Turnstile 人机验证结果

    Args:
        data: 前端拿到的人机校验 token
        svc: 账号业务服务(内部请求 Cloudflare siteverify 接口)

    Returns:
        dict: {"success": bool} 是否通过人机校验
    """
    return await svc.two_step_verification(data)


@router_account.get('/accounts/check-username/{username}/', summary="检测用户名是否已经存在", tags=[Tag.account])
async def check_username(username: Annotated[str, "检测用户名是否已经存在"],
                         svc: AccountService = Depends(get_account_service)) -> dict:
    """
    注册前的用户名可用性检测

    先做格式合法性校验, 再查库判断是否已被占用。

    Args:
        username: 待检测的用户名
        svc: 账号业务服务

    Returns:
        dict: {"exists": bool} 是否已存在
    """

    try:
        is_exists = await svc.check_username(username)
        return {"exists": is_exists}
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router_account.patch('/accounts/credential/', summary="更新用户认证信息",
                      response_model=AccountInfo, tags=[Tag.account])
async def credential(data: Annotated[UpdateCredential, "更新用户认证信息"],
                     request: Annotated[Request, "请求对象"],
                     svc: AccountService = Depends(get_account_service)):
    """
    更新用户认证信息(目前支持修改用户名)

    账户ID取自令牌载荷, 不接受客户端传入, 避免越权修改他人账号。

    Args:
        data: 认证信息变更入参(类型 + 新值)
        request: 请求对象, 携带当前登录账户ID
        svc: 账号业务服务

    Returns:
        AccountInfo: 更新后的账号信息
    """
    try:
        instance = await svc.change_credential(request.state.account_id, data)
        return instance
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
