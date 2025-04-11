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
from datetime import timedelta, datetime
from typing import List, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Security, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic_core import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status

from .models import Account, AccountCreate, AccountPublic, AccountPublicCommon, AccountPasswordChange, \
    AccountPasswordReset, RefreshToken, AccessToken, App, AppAccessToken, AppRefreshToken

from src.tuiwen.utils.jwt_token import generate_jwt_token, verify_jwt_token
from src.tuiwen.dependencies import get_current_user, check_authentication, oauth2_scheme, get_session
from src.tuiwen.router import router_public
from src.tuiwen.utils.utils import get_random_salt, convert_to_cst_time
from src.tuiwen.core import settings

SCOPES_BASIC = 'basic'

##################################################### oauth ############################################################
router_oauth = APIRouter(prefix="/oauth", tags=["oauth"], dependencies=[Depends(check_authentication)])


@router_public.post("/oauth/authorize/password/", tags=["oauth"],
                    summary="用户使用用户名或邮箱进和密码进行认证获取刷新令牌",
                    response_model=RefreshToken)
async def authorize(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                    session: AsyncSession = Depends(get_session)):
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
            Account.password == form_data.password,
            Account.is_active == True)
        instance = (await session.exec(statement)).first()
        assert instance is not None, '请重新检查你的用户名和密码'
    except AssertionError as e:
        raise HTTPException(status_code=404, detail=str(e), headers={'WWW-Authenticate': 'Bearer'})

    # 作废之前的salt
    instance.salt = get_random_salt(8)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    data = {"account_id": instance.account_id, "salt": instance.salt, 'scopes': SCOPES_BASIC}

    refresh_token = generate_jwt_token(data, expires_in=timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
                                       grant_type="refresh_token")

    data.update(**{'jwt_account_id': instance.account_id})
    access_token = generate_jwt_token(data, grant_type="access_token")

    return RefreshToken(refresh_token=refresh_token, access_token=access_token,
                        expires_in=int(timedelta(days=28).total_seconds()),
                        account_id=instance.account_id)


@router_oauth.get("/refresh-token/{account_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
                  response_model=AccessToken)
async def refresh_token(account_id: str, refresh_token: str = Depends(oauth2_scheme)):
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
                                      expires_in=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))

    return AccessToken(access_token=access_token, account_id=account_id)


@router_oauth.get("/test-oauth/", summary="测试接口(基础权限)")
def test_oauth(user: Account = Depends(get_current_user)) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


@router_oauth.get("/test-oauth-admin/", summary="测试接口(需要更高权限)")
def test_oauth_admin(user: Account = Security(get_current_user, scopes=['admin'])) -> Any:
    return {"message": f"hello word, 欢迎您,{user.account_id}"}


##################################################### app ##############################################################

router_app = APIRouter(prefix="/oauth/app", tags=["oauth"], dependencies=[Depends(check_authentication)])


@router_public.get("/oauth/app/authorize/{app_id}/{app_secret}/client_credential/", summary="app进行认证获取刷新令牌",
                   response_model=AppRefreshToken, tags=["oauth", ])
async def app_authorize(app_id: str, app_secret: str, session: AsyncSession = Depends(get_session)):
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
        reuslts = await session.exec(statement)

        instance = reuslts.first()

        assert instance is not None, '请重新检查你的app_id和app_secret'
    except AssertionError as e:
        raise HTTPException(status_code=404, detail=str(e), headers={'WWW-Authenticate': 'Bearer'})

    # 作废之前的salt
    instance.salt = get_random_salt()
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    data = {"app_id": instance.app_id, "salt": instance.salt, 'scopes': SCOPES_BASIC}

    refresh_token = generate_jwt_token(data, expires_in=timedelta(days=7), grant_type="refresh_token")

    data.update(**{'jwt_app_id': instance.app_id})
    access_token = generate_jwt_token(data, grant_type="access_token")

    return AppRefreshToken(refresh_token=refresh_token, access_token=access_token,
                           expires_in=int(timedelta(days=28).total_seconds()),
                           app_id=instance.app_id)


@router_app.get("/refresh-token/{app_id}/refresh_token/", summary="使用刷新令牌进行更新获取权限令牌",
                response_model=AppAccessToken)
def app_refresh_token(app_id: str, refresh_token: str = Depends(oauth2_scheme)):
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
@router_public.get("/", tags=["root"], summary="服务检查检查")
async def health_check() -> dict[str, Any]:
    current_time = convert_to_cst_time(datetime.now())
    return {"message": "ok", "gmt_created": current_time}


########################################################################################################################

router_account = APIRouter(prefix="/accounts", tags=["account", ], dependencies=[Depends(check_authentication)])


@router_public.post("/accounts/register/", summary="用户注册", tags=["account", ],
                    response_model=AccountPublic, status_code=status.HTTP_201_CREATED)
async def register(account: AccountCreate, session: AsyncSession = Depends(get_session)):
    # 执行原生sql
    # result = (await session.exec(text("select id from tuiwen_account"))).all()
    # print(result)
    try:
        account_data = AccountCreate.model_dump(account)
        instance = Account(**account_data)

        if not instance.username:
            instance.username = instance.account_id

        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="该邮箱已被注册,如果您是该邮箱的拥有者,请前往登录")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return instance


@router_account.get("/{account_id}/", summary="查询账户信息", response_model=AccountPublic,
                    responses={
                        404: {"description": "no such account"}
                    })
async def get_account(account_id: str, session: AsyncSession = Depends(get_session)):
    statement = select(Account).where(Account.account_id == account_id)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=404, detail="no such account")
    return instance


@router_account.put("/{account_id}/", summary="更新账户基本信息", response_model=AccountPublic)
async def update_account(account_id: str, account: AccountPublicCommon, session: AsyncSession = Depends(get_session),
                         user: Account = Depends(get_current_user)):
    try:
        assert user.account_id == account_id, '请不要跨账户操作'
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    statement = select(Account).where(Account.account_id == account_id)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such account")

    account_data = account.model_dump(exclude_unset=True)
    instance.sqlmodel_update(account_data)

    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在!")
    return instance


@router_account.get("/search/{keyword}/", summary="通过关键词搜索账户", response_model=List[AccountPublic])
async def search(keyword: str, session: AsyncSession = Depends(get_session), offset: int = 0,
                 limit: Annotated[int, Query(le=10)] = 10, ):
    statement = select(Account).where(
        or_(Account.username.contains(keyword), Account.nick_name.contains(keyword))).offset(offset).limit(limit)
    ds = (await session.exec(statement)).all()

    return ds


@router_public.put("/accounts/password/reset/", summary="账号密码重置", tags=['account'],
                   response_model=AccountPublic)
async def password_reset(account: AccountPasswordReset, session: AsyncSession = Depends(get_session)):
    statement = select(Account).where(Account.account_id == account.account_id)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such account")

    # 判断验证码是否一致 todo
    try:
        assert account.code == "666666", "你的验证码不对"
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    account_data = Account.model_dump(account, exclude_unset=True, exclude={'account_id'})
    instance.sqlmodel_update(account_data)
    instance.salt = get_random_salt(8)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)

    return instance


@router_account.put("/password/change/", summary="账号密码修改", response_model=AccountPublic,
                    status_code=status.HTTP_200_OK)
async def password_change(request: Request, account: AccountPasswordChange,
                          session: AsyncSession = Depends(get_session), ):
    statement = select(Account).where(Account.account_id == request.state.account_id,
                                      Account.password == account.password_current)
    instance = (await session.exec(statement)).first()
    if not instance:
        raise HTTPException(status_code=400, detail="原密码不对,请重新输入原密码")

    try:
        assert account.password_new != instance.password, "新密码不能和旧密码相同"
    except AssertionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    instance.password = account.password_new
    instance.salt = get_random_salt(8)
    session.add(instance)
    await session.commit()
    await session.refresh(instance)

    return instance
