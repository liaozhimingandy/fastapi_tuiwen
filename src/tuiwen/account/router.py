#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: FastAPIDemo
    @File： router.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/1/19 09:45
    @Desc: 
=================================================
"""
import re
from datetime import timedelta, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Security, Request, status, Body, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from pydantic_core import ValidationError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from ..utils import hash_password, redis_set, redis_get, redis_delete
from ..core.database import add_instance
from .models import Account, AccountCreate, AccountPublic, AccountPublicCommon, AccountPasswordChange, \
    AccountPasswordReset, RefreshToken, AccessToken, App, AppAccessToken, AppRefreshToken, CodeVerify, \
    TurnstileVerifyToken, UpdateCredential

from src.tuiwen.utils import generate_jwt_token, verify_jwt_token, get_random_salt, convert_to_cst_time
from src.tuiwen.core import Tag
from src.tuiwen.models import PageResponse
from src.tuiwen.dependencies import get_current_user, get_session, oauth2_scheme
from src.tuiwen.core.config import get_settings
from ..utils.email_service import send_reset_pwd_email
from ..utils.utils import validate_username

config = get_settings()

SCOPES_BASIC = 'basic'

##################################################### oauth ############################################################
router_oauth = APIRouter(prefix="/oauth", tags=[Tag.oauth])
router_public = APIRouter()


@router_public.post("/oauth/authorize/password/",
                    summary="用户使用用户名或邮箱进和密码进行认证获取刷新令牌", tags=[Tag.oauth],
                    response_model=RefreshToken)
async def authorize(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                    session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
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
        statement = select(Account).where(
            or_(Account.email == form_data.username, Account.username == form_data.username),
            Account.is_active == True)
        instance = (await session.exec(statement)).first()
        assert instance is not None and instance.password == hash_password(form_data.password,
                                                                           instance.salt), '请重新检查你的用户名和密码'

    except AssertionError as e:
        raise HTTPException(status_code=404, detail=str(e), headers={'WWW-Authenticate': 'Bearer'})

    data = {"account_id": instance.account_id, "salt": instance.salt, 'scopes': SCOPES_BASIC}
    refresh_token = generate_jwt_token(data, expires_in=timedelta(minutes=get_settings().REFRESH_TOKEN_EXPIRE_MINUTES),
                                       grant_type="refresh_token")

    data.update(**{'jwt_account_id': instance.account_id})
    access_token = generate_jwt_token(data, grant_type="access_token")

    return RefreshToken(refresh_token=refresh_token, access_token=access_token,
                        expires_in=int(timedelta(days=28).total_seconds()),
                        account_id=instance.account_id)


@router_oauth.get("/refresh-token/{account_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
                  tags=[Tag.oauth], response_model=AccessToken)
async def refresh_token(account_id: Annotated[str, "账户ID"],
                        refresh_token: Annotated[str, "刷新令牌"] = Depends(oauth2_scheme)):
    """
    使用刷新令牌进行更新获取权限令牌,请使用postman测试,header携带认证信息,后续会实现,refresh_token有效期为7天,请妥善保管,重新登录认证后,
    该token作废; <br>

    Args: <br>
        account_id: 账户唯一标识 <br>
        refresh_token: 刷新token <br>

    Returns: <br>
        请求token <br>

    """
    payload = verify_jwt_token(refresh_token, grant_type='refresh_token')
    try:
        assert account_id == payload.get('account_id'), '请检查token是否为该账户的token同时为刷新令牌,请不要跨账户操作'
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    data = {"account_id": account_id, "salt": payload.get('salt'), 'jwt_account_id': account_id, 'scopes': SCOPES_BASIC}

    access_token = generate_jwt_token(data, grant_type="access_token",
                                      expires_in=timedelta(minutes=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES))

    return AccessToken(access_token=access_token, account_id=account_id)


@router_oauth.get("/test-oauth/", summary="测试接口(基础权限)")
async def test_oauth(user: Annotated[Account, "账户信息"] = Depends(get_current_user)) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


@router_oauth.get("/test-oauth-admin/", summary="测试接口(需要更高权限)")
async def test_oauth_admin(
        user: Annotated[Account, "认证的用户信息"] = Security(get_current_user, scopes=['admin'])) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


##################################################### app ##############################################################

router_app = APIRouter(prefix="/oauth/app", tags=[Tag.app])


@router_public.get("/oauth/app/authorize/{app_id}/{app_secret}/client_credential/", summary="app进行认证获取刷新令牌",
                   response_model=AppRefreshToken, tags=[Tag.app], include_in_schema=False)
async def app_authorize(app_id: Annotated[str, "app_id"], app_secret: Annotated[str, "密钥"],
                        session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    """
    app进行认证获取刷新令牌 <br>

    Args: <br>
        app_id: 应用唯一标识 <br>
        app_secret: 应用密钥 <br>
        session: 数据库操作会话依赖 <br>

    Returns: <br>
        令牌信息或报错信息 <br>

    """

    try:
        statement = select(App).where(App.app_id == app_id, App.app_secret == app_secret, App.is_active == True)
        dataset = await session.exec(statement)

        instance = dataset.first()

        assert instance is not None, '请重新检查你的app_id和app_secret'
    except AssertionError as e:
        raise HTTPException(status_code=404, detail=str(e), headers={'WWW-Authenticate': 'Bearer'})

    # 作废之前的salt
    instance.salt = get_random_salt()
    instance = await add_instance(session, instance)
    data = {"app_id": instance.app_id, "salt": instance.salt, 'scopes': SCOPES_BASIC}

    refresh_token = generate_jwt_token(data, expires_in=timedelta(days=7), grant_type="refresh_token")

    data.update(**{'jwt_app_id': instance.app_id})
    access_token = generate_jwt_token(data, grant_type="access_token")

    return AppRefreshToken(refresh_token=refresh_token, access_token=access_token,
                           expires_in=int(timedelta(days=28).total_seconds()),
                           app_id=instance.app_id)


@router_app.get("/refresh-token/{app_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
                response_model=AppAccessToken, tags=[Tag.app])
async def app_refresh_token(app_id: Annotated[str, "app id"],
                            refresh_token: Annotated[str, "刷新令牌"] = Depends(oauth2_scheme)):
    """
    使用刷新令牌进行更新获取权限令牌,请使用postman测试,header携带认证信息,后续会实现,refresh_token有效期为7天,请妥善保管,重新登录认证后,
    该token作废;

    Args:
        app_id: 账户唯一标识 <br>
        refresh_token: 刷新token <br>

    Returns:
        请求token

    """
    payload = verify_jwt_token(refresh_token, grant_type='refresh_token')
    try:
        assert get_account == payload.get('app_id'), '请检查token是否为该账户的token,请不要跨账户操作'
    except AssertionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = {"app_id": app_id, "salt": payload.get('salt'), 'jwt_app_id': app_id, 'scopes': SCOPES_BASIC}

    access_token = generate_jwt_token(data, grant_type="access_token", expires_in=timedelta(hours=2))

    return AppAccessToken(access_token=access_token, app_id=app_id)


########################################################################################################################
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
                   session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    # 执行原生sql
    # result = (await session.exec(text("select id from tuiwen_account"))).all()
    # print(result)

    account_data = account.model_dump()
    instance = Account(**account_data)

    if not instance.username:
        instance.username = instance.account_id

    # 判断数据库是否存在
    exist_stmt = select(Account).where(or_(Account.email == func.lower(instance.email),
                                           Account.username == func.lower(instance.username)))
    exist_user = (await session.exec(exist_stmt)).first()

    if exist_user:
        # 精准判断是哪个字段重复，返回对应提示，用户体验更好
        if exist_user.email.lower() == instance.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该邮箱已被注册,如您是账号所有者,请直接登录"
            )
        if exist_user.username.lower() == instance.username.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该账号ID已被占用，请更换后重试"
            )

    # 更新用户信息
    instance.salt = get_random_salt(8)
    instance.password = hash_password(front_md5=instance.password, salt=instance.salt)

    try:
        instance = await add_instance(session, instance)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="注册失败,该账号信息已被占用,请重试")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return instance


@router_public.get("/accounts/{account_id}/", summary="查询账户信息",
                   response_model=AccountPublic,
                   name="get_account_public",
                   tags=[Tag.account, ],
                   responses={
                       404: {"description": "no such account"}
                   })
async def get_account(account_id: Annotated[str, "账户ID"],
                      session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = select(Account).where(Account.account_id == account_id)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=404, detail="no such account")
    return instance


@router_account.put("/{account_id}/", summary="更新账户基本信息", response_model=AccountPublic)
async def update_account(account_id: Annotated[str, "账户ID"],
                         account: Annotated[AccountPublicCommon, Body(..., description="更新的账户信息")],
                         session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session),
                         user: Annotated[Account, "认证的用户信息"] = Depends(get_current_user)):
    try:
        assert user.account_id == account_id, '请不要跨账户操作'
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    statement = select(Account).where(Account.account_id == account_id)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such account")

    # 排除被更新字段
    forbidden_fields = {"account_id", "username", "email", "mobile", "id", "password", "salt", "is_active",
                        "user_type", "im_id", "gmt_created", "gmt_modified"}

    account_data = account.model_dump(exclude_unset=True, exclude=forbidden_fields)
    instance.sqlmodel_update(account_data)

    instance = await add_instance(session, instance)

    return instance


@router_account.get("/search/{keyword}/", summary="通过关键词搜索账户", response_model=PageResponse[AccountPublic])
async def search(keyword: Annotated[str, "关键词"], *, session: AsyncSession = Depends(get_session),
                 offset: Annotated[int, "偏移量"] = 0,
                 limit: Annotated[int, Query(le=10)] = 10, ) -> PageResponse[AccountPublic]:
    cleaned = keyword.strip().lower()
    statement = select(Account).where(
        or_(Account.username.contains(cleaned), Account.nick_name.contains(cleaned))).offset(offset).limit(limit)
    dataset = (await session.exec(statement)).all()

    return PageResponse(items=dataset, total=len(dataset), page_size=limit)

# 邮箱正则（通用标准正则，兼容绝大多数邮箱）
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

@router_public.post("/accounts/send/code/", summary="发送验证码", tags=[Tag.account])
async def account_send_code(data: Annotated[CodeVerify, "验证码信息"],
                            background_tasks: Annotated[BackgroundTasks, "后台任务"],
                            session: AsyncSession = Depends(get_session),):
    import random
    # send_notification
    code = data.model_dump(exclude={'code'})
    instance_code = CodeVerify(**code, code="".join(random.choices("0123456789", k=6)))

    if not EMAIL_PATTERN.match(instance_code.account):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱格式不正确，请输入合法邮箱地址"
        )

    # 判断用户是否存在
    stmt = select(Account).where(Account.email == instance_code.account)
    instance = (await session.exec(stmt)).first()

    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="本系统没有这个邮箱的用户,请确认")

    data = {
        'code': instance_code.code,
        'expire': 30,
        'to_email': instance_code.account
    }

    # ======================
    # 1小时发送限流
    # ======================
    key = f"tw:dev:reset_pwd:account:{instance_code.account}"
    if await redis_get(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证码已发送，请30分钟后再次尝试"
        )

    # 存到redis
    await redis_set(key, instance_code.code, expire=config.REDIS_EXPIRE)
    # 后台发送邮箱通知
    background_tasks.add_task(send_reset_pwd_email, **data)
    return {"message": "验证码已经发送至你的邮箱,请查收!"}


@router_public.put("/accounts/password/reset/", summary="账号密码重置", tags=[Tag.account],
                   response_model=AccountPublic)
async def password_reset(account: Annotated[AccountPasswordReset, Body(..., description="密码充值的必要信息")],
                         session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = select(Account).where(or_(Account.username == account.username,
                                          Account.email == account.username))
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such account")

    # 按业界规范构造 key
    redis_key = f"tw:dev:reset_pwd:account:{account.username}"

    # 从 Redis 获取验证码
    correct_code = await redis_get(redis_key)

    # 校验逻辑
    if not correct_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码已过期或未发送"
        )

    if correct_code != account.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码不正确"
        )

        # 验证通过后立即删除验证码，防止重复使用
    await redis_delete(redis_key)

    # 更新用户信息
    instance.salt = get_random_salt(8)
    instance.password = hash_password(front_md5=account.password, salt=instance.salt)

    # 保存到数据库
    instance = await add_instance(session, instance)

    return instance


@router_account.put("/password/change/", summary="账号密码修改", response_model=AccountPublic,
                    status_code=status.HTTP_200_OK)
async def password_change(request: Annotated[Request, "请求对象"],
                          account: Annotated[AccountPasswordChange, Body(..., description="修改密码的必要入参")],
                          session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session), ):
    statement = select(Account).where(Account.account_id == request.state.account_id,
                                      Account.password == hash_password(account.password_current, request.state.salt))
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=400, detail="原密码不对,请重新输入原密码")

    try:
        assert account.password_new != instance.password, "新密码不能和旧密码相同"
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    instance.salt = get_random_salt(8)
    instance.password = hash_password(front_md5=account.password_new, salt=instance.salt)

    instance = await add_instance(session, instance)

    return instance


# 人机检测
@router_public.post('/auth/two_step_verification/', summary="人机检测校验接口", tags=[Tag.oauth],)
async def two_step_verification(data: Annotated[TurnstileVerifyToken, Body(..., description="人机检测校验接口")]):
    payload = {
        "secret": get_settings().TURNSTILE_SECRET_KEY,
        "response": data.cf_turnstile_token
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=payload
        )
        return {"success": r.json()["success"]}


@router_account.get('/check-username/{username}/', summary="检测用户名是否已经存在", tags=[Tag.account])
async def check_username(username: Annotated[str, "检测用户名是否已经存在"], session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)) -> dict:
    print(username)
    ok, detail = validate_username(username=username)
    if not ok:
        return {"exists": True, "detail": detail}

    stmt =  select(Account).where(Account.username == username.strip().lower()).limit(1)
    exists = (await session.exec(stmt)).first()
    return {"exists": bool(exists)}


@router_account.patch('/credential/', summary="更新用户认证信息",
                      response_model=AccountPublic,tags=[Tag.account])
async def credential(data: Annotated[UpdateCredential, "更新用户认证信息"],
                    request: Annotated[Request, "请求对象"],
                    session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    new_val = data.new_value.strip()
    # ---------------------- 修改用户名（仅校验登录态，无需密码） ----------------------
    if data.type == "username":
        ok, desc = validate_username(new_val)

        if not ok: raise HTTPException(status_code=400, detail=str(desc))

        stmt = select(Account).where(Account.username == data.new_value.strip().lower()).limit(1)
        exists = (await session.exec(stmt)).first()

        if exists:
            raise HTTPException(status_code=400, detail=str("该用户已被占用"))

        stmt = select(Account).where(Account.account_id == request.state.account_id)
        instance = (await session.exec(stmt)).first()

        instance.username = new_val.strip().lower()
        instance = await add_instance(session, instance)

    return instance





