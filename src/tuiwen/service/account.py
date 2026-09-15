import re
from datetime import timedelta
from typing import Annotated
import random

import httpx

from account.router import SCOPES_BASIC
from src.tuiwen.common.exceptions import BizError
from src.tuiwen.common.exceptions import EmailAlreadyRegisteredError, UsernameAlreadyUsedError
from src.tuiwen.account.models import AccountCreate, Account, AccountPublicCommon, CodeVerify, TurnstileVerifyToken, \
    UpdateCredential, AccountPasswordChange, AccountPasswordReset, RefreshToken, AccessToken
from src.tuiwen.dal.account import AccountDAO
from src.tuiwen.utils import get_random_salt, hash_password

from sqlmodel import select, or_

from src.tuiwen.core import get_settings
from src.tuiwen.utils.redis_util import RedisKey, redis_get, redis_set, redis_delete
from src.tuiwen.utils.utils import validate_username
from utils import generate_jwt_token, verify_jwt_token

# 邮箱正则（通用标准正则，兼容绝大多数邮箱）
MAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

class AccountService:
    dao: AccountDAO

    async def register(self, dto: AccountCreate):
        account_data = dto.model_dump()
        instance = Account(**account_data)

        # 用户名兜底
        if not instance.username:
            instance.username = instance.account_id

        # 查重
        exist_user = await self.dao.get_account_by_email_or_username(
            email=instance.mail,
            username=instance.username
        )

        if exist_user:
            # 区分冲突字段抛出不同提示
            if exist_user.mail.lower() == instance.mail.lower():
                raise EmailAlreadyRegisteredError(
                    code=400,
                    message="该邮箱已被注册,如您是账号所有者,请直接登录"
                )
            if exist_user.username.lower() == instance.username.lower():
                raise UsernameAlreadyUsedError(
                    code=400,
                    message="该账号ID已被占用，请更换后重试"
                )

        # 更新用户信息
        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=instance.password, salt=instance.salt)

        # 新增数据库记录
        # 注意：按照你的DAO规范，service层不做commit，commit交给上层/路由外层事务
        await self.dao.create(instance)
        return instance

    async def get_account(self, account_id: str):
        return await self.dao.get_by_unique_field("account_id", account_id)

    async def update_account(self, account_id: str, account: AccountPublicCommon):
        instance = await self.dao.get_by_unique_field("account_id", account_id)
        if not instance:
            raise BizError(code=400, message="no such account")

        # 排除被更新字段
        forbidden_fields = {"account_id", "username", "mail", "mobile", "id", "password", "salt", "is_active",
                            "user_type", "im_id", "gmt_created", "gmt_modified"}

        account_data = account.model_dump(exclude_unset=True, exclude=forbidden_fields)
        instance.sqlmodel_update(account_data)

        return await self.dao.partial_update(instance.id, instance)

    async def search(self, keyword: str, offset: int, limit: int):
        cleaned = keyword.strip().lower()
        statement = select(Account).where(
            or_(Account.username.contains(cleaned), Account.nick_name.contains(cleaned))).offset(offset).limit(limit)

        with self.dao.read_db() as session:
            return (await session.exec(statement)).all()

    async def account_send_code(self, data: Annotated[CodeVerify, "验证码信息"], ):
        # send_notification
        code = data.model_dump(exclude={'code'})
        instance_code = CodeVerify(**code, code="".join(random.choices("0123456789", k=6)))
        if not MAIL_PATTERN.match(instance_code.account):
            raise BizError(
                code=400,
                message="邮箱格式不正确，请输入合法邮箱地址"
            )

        # 判断用户是否存在
        instance = await self.dao.get_by_unique_field("mail", instance_code.account)

        if not instance:
            raise BizError(code=404, message="本系统没有这个邮箱的用户,请确认")

        # ======================
        # 1小时发送限流
        # ======================
        key = RedisKey.reset_pwd_code(instance_code.account)
        if await redis_get(key):
            raise BizError(
                code=400,
                message="验证码已发送，请30分钟后再次尝试"
            )

        # 存到redis
        await redis_set(key, instance_code.code, expire=get_settings().REDIS_EXPIRE)

        data = {
            'code': instance_code.code,
            'expire': 30,
            'to_mail': instance_code.account
        }

        return data

    async def reset_password(self, account: Annotated[AccountPasswordReset, '重置密码必要信息']):
        instance = await self.dao.get_account_by_email_or_username(mail=account.username)

        if not instance:
            raise BizError(code=404, message="no such account")

        # 按业界规范构造 key
        redis_key = RedisKey.reset_pwd_code(instance.username)

        # 从 Redis 获取验证码
        correct_code = await redis_get(redis_key)

        # 校验逻辑
        if not correct_code:
            raise BizError(
                code=404,
                message="验证码已过期或未发送"
            )

        if correct_code != account.code:
            raise BizError(code=400, message="验证码不正确")

            # 验证通过后立即删除验证码，防止重复使用
        await redis_delete(redis_key)

        # 更新用户信息
        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=account.password, salt=instance.salt)

        # 保存到数据库
        return await self.dao.partial_update(instance)

    async def authorize(self, username:str, password: str):
        try:
            instance = await self.dao.get_account_by_email_or_username(mail=username, username=username)
            assert instance is not None and instance.password == hash_password(password, instance.salt), '请重新检查你的用户名和密码'

        except AssertionError as e:
            raise BizError(code=400, message=str(e))

        data = {"account_id": instance.account_id, "salt": instance.salt, 'scopes': 'basic'}
        refresh_token = generate_jwt_token(data, expires_in=timedelta(minutes=get_settings().REFRESH_TOKEN_EXPIRE_MINUTES),
                                           grant_type="refresh_token")

        data.update(**{'jwt_account_id': instance.account_id})
        access_token = generate_jwt_token(data, grant_type="access_token")

        return RefreshToken(refresh_token=refresh_token, access_token=access_token,
                            expires_in=int(timedelta(minutes=get_settings().REFRESH_TOKEN_EXPIRE_MINUTES).total_seconds()),
                            account_id=instance.account_id)

    @classmethod
    async def refresh_token(cls, account_id: str, refresh_token: str):
        try:
            payload = verify_jwt_token(refresh_token, grant_type='refresh_token')
            assert account_id == payload.get('account_id'), '请检查token是否为该账户的token同时为刷新令牌,请不要跨账户操作'
        except AssertionError as e:
            raise BizError(code=401, message=str(e))
        except Exception as e:
            raise BizError(code=401, message=str(e))

        data = {"account_id": account_id, "salt": payload.get('salt'), 'jwt_account_id': account_id,
                'scopes': SCOPES_BASIC}

        access_token = generate_jwt_token(data, grant_type="access_token",
                                          expires_in=timedelta(minutes=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES))

        return AccessToken(access_token=access_token, account_id=account_id)

    @classmethod
    async def two_step_verification(cls, data: Annotated[TurnstileVerifyToken, "人机监测的token"]):
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

    async def check_username(self, username: str):
        ok, detail = validate_username(username=username)
        if not ok:
            raise BizError(code=400, message=detail)

        is_exists = await self.dao.exists(username=username)
        return is_exists

    async def change_credential(self, account_id: str, data: Annotated[UpdateCredential, "更新用户认证信息"]):
        new_val = data.new_value.strip()

        if data.type == 'username':
            ok, desc = validate_username(new_val)
            if not ok: raise BizError(code=400, message=str(desc))

            is_exists = await self.dao.exists(username=data.new_value.strip().lower())
            if is_exists:
                raise BizError(code=400, message=str("该用户已被占用"))

            instance = await self.dao.get_by_unique_field("account_id", account_id)
            instance.username = new_val.strip().lower()

            return await self.dao.update(instance)
        return None

    async def change_password(self, account_id: str, salt, account: Annotated[AccountPasswordChange, '修改密码必要的参数']):
        try:
            instance = await self.dao.get_by_fields(account_id=account_id, password=hash_password(account.password_current, salt))
            if not instance:
                raise BizError(code=400, message="原密码不对,请重新输入原密码")
            assert account.password_new != instance.password, "新密码不能和旧密码相同"
        except AssertionError as e:
            raise BizError(code=400, message=str(e))

        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=account.password_new, salt=instance.salt)

        return self.dao.update(instance)

