from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, status, Depends, Request, Query, HTTPException, BackgroundTasks, Security
from fastapi.security import OAuth2PasswordRequestForm
from starlette.responses import RedirectResponse

from common.exceptions import BizError
from src.tuiwen.dependencies import get_account_service, get_current_user, oauth2_scheme
from src.tuiwen.service.account import AccountService
from src.tuiwen.account.models import RefreshToken, AccountPublic, AccountCreate, Account, AccountPublicCommon, \
    CodeVerify, TurnstileVerifyToken, UpdateCredential, AccountPasswordChange, AccountPasswordReset, AccessToken
from src.tuiwen.core import Tag
from src.tuiwen.models import PageResponse
from src.tuiwen.utils.mail_service import send_reset_pwd_mail
from src.tuiwen.utils.utils import validate_username, convert_to_cst_time

router_oauth = APIRouter(prefix="/oauth", tags=[Tag.oauth])
router_public = APIRouter(prefix='/')


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

    try:
        return await svc.authorize(username=form_data.username, password=form_data.password)
    except BizError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router_oauth.get("/refresh-token/{account_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
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
    try:
        return await svc.refresh_token(account_id, token)
    except BizError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router_oauth.get("/test-oauth/", summary="测试接口(基础权限)")
async def test_oauth(user: Annotated[Account, "账户信息"] = Depends(get_current_user)) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


@router_oauth.get("/test-oauth-admin/", summary="测试接口(需要更高权限)")
async def test_oauth_admin(
        user: Annotated[Account, "认证的用户信息"] = Security(get_current_user, scopes=['admin'])) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


@router_public.get("/health-check/", tags=["health"], summary="服务检查检查")
async def health_check() -> dict[str, Any]:
    current_time = convert_to_cst_time(datetime.now())
    return {"message": "ok", "gmt_created": current_time}

@router_public.get("/", tags=["root"], summary="根路径", include_in_schema=False)
async def root(request: Annotated[Request, "请求对象"]) -> RedirectResponse:
    url_for_redirect = request.url_for("health_check")
    return RedirectResponse(url=url_for_redirect, status_code=301)


########################################################################################################################

router_account = APIRouter(prefix="/accounts", tags=[Tag.account, ])


@router_public.post("/accounts/register/", summary="用户注册", tags=[Tag.account],
                    response_model=AccountPublic, status_code=status.HTTP_201_CREATED)
async def register(account: Annotated[AccountCreate, Body(..., description="用户信息")],
                   svc: AccountService = Depends(get_account_service)):
    try:
        instance = await svc.register(account)
        # 事务提交，保持你的DAO规范：DAO只add，上层commit
        await svc.dao.write_db.commit()
        await svc.dao.write_db.refresh(instance)
        return instance

    except BizError as e:
        await svc.dao.write_db.rollback()
        # API层统一转HTTP异常
        raise HTTPException(
            status_code=e.code,
            detail=e.message
        )


@router_public.get("/accounts/{account_id}/", summary="查询账户信息",
                   response_model=AccountPublic,
                   name="get_account_public",
                   tags=[Tag.account, ],
                   responses={
                       404: {"description": "no such account"}
                   })
async def get_account(account_id: Annotated[str, "账户ID"],
                      svc: AccountService = Depends(get_account_service)):
    instance = await svc.get_account(account_id)
    if not instance:
        raise HTTPException(status_code=404, detail="no such account")
    return instance


@router_account.put("/{account_id}/", summary="更新账户基本信息", response_model=AccountPublic)
async def update_account(account_id: Annotated[str, "账户ID"],
                         account: Annotated[AccountPublicCommon, Body(..., description="更新的账户信息")],
                         svc: AccountService = Depends(get_account_service),
                         user: Annotated[Account, "认证的用户信息"] = Depends(get_current_user)):
    try:
        assert user.account_id == account_id, '请不要跨账户操作'
        return await svc.update_account(account_id, account)
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BizError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router_account.get("/search/{keyword}/", summary="通过关键词搜索账户", response_model=PageResponse[AccountPublic])
async def search(keyword: Annotated[str, "关键词"], *, svc: AccountService = Depends(get_account_service),
                 offset: Annotated[int, "偏移量"] = 0,
                 limit: Annotated[int, Query(le=10)] = 10, ) -> PageResponse[AccountPublic]:
    dataset = await svc.search(keyword, offset, limit)
    return PageResponse(items=dataset, total=len(dataset), page_size=limit)


@router_public.post("/accounts/send/code/", summary="发送验证码", tags=[Tag.account])
async def account_send_code(data: Annotated[CodeVerify, "验证码信息"],
                            background_tasks: Annotated[BackgroundTasks, "后台任务"],
                            svc: AccountService = Depends(get_account_service)):
    result = await svc.account_send_code(data)
    # 后台发送邮箱通知
    background_tasks.add_task(send_reset_pwd_mail, **result)
    return {"message": "验证码已经发送至你的邮箱,请查收!"}


@router_public.put("/accounts/password/reset/", summary="账号密码重置", tags=[Tag.account],
                   response_model=AccountPublic)
async def password_reset(account: Annotated[AccountPasswordReset, Body(..., description="密码重置的必要信息")],
                         svc: AccountService = Depends(get_account_service)):
    try:
        return await svc.reset_password(account)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router_account.put("/password/change/", summary="账号密码修改", response_model=AccountPublic,
                    status_code=status.HTTP_200_OK)
async def password_change(request: Annotated[Request, "请求对象"],
                          account: Annotated[AccountPasswordChange, Body(..., description="修改密码的必要入参")],
                          svc: AccountService = Depends(get_account_service)):
    try:
        return await svc.change_password(request.state.account_id, request.state.salt, account)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# 人机检测
@router_public.post('/auth/two_step_verification/', summary="人机检测校验接口", tags=[Tag.oauth], )
async def two_step_verification(data: Annotated[TurnstileVerifyToken, Body(..., description="人机检测校验接口")],
                                svc: AccountService = Depends(get_account_service)):
   return await svc.two_step_verification(data)


@router_account.get('/check-username/{username}/', summary="检测用户名是否已经存在", tags=[Tag.account])
async def check_username(username: Annotated[str, "检测用户名是否已经存在"],
                         svc: AccountService = Depends(get_account_service)) -> dict:

    try:
        is_exists = await svc.check_username(username)
        return {"exists": is_exists}
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router_account.patch('/credential/', summary="更新用户认证信息",
                      response_model=AccountPublic, tags=[Tag.account])
async def credential(data: Annotated[UpdateCredential, "更新用户认证信息"],
                     request: Annotated[Request, "请求对象"],
                     svc: AccountService = Depends(get_account_service)):
    try:
        instance = await svc.change_credential(request.state.account_id, data)
        return instance
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))