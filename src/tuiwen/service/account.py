"""
账号业务服务层(AccountService)

职责:
    1. 注册: 用户名兜底、邮箱/用户名唯一性校验、密码加盐哈希
    2. 登录: 校验凭据并签发 refresh_token / access_token
    3. 令牌: 用 refresh_token 换新的 access_token
    4. 密码: 发送验证码(Redis 存储 + 限流)、重置密码、修改密码
    5. 资料: 账户查询、资料更新、用户名变更、用户名查重
    6. 安全: Cloudflare Turnstile 人机检测

不负责:
    1. 事务提交(commit) —— 按 DAO 规范由上层/路由控制
    2. HTTP 相关处理 —— BizError 由 API 层转换为 HTTPException

分层位置:
    API → AccountService → AccountDAO → PostgreSQL (Redis 存验证码 / SMTP 发信)
"""
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated
import random

import httpx
from sqlmodel import select, or_

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.common.exceptions import EmailAlreadyRegisteredError, UsernameAlreadyUsedError
# 模型统一从 model 包绝对导入(原 "from model.account" 是裸导入, 只在把 src/tuiwen 也加入
# sys.path 时才成立, 与项目「唯一源根=项目根」的约定冲突);
# 重构后账户字段与令牌/验证码模型分别位于 account / oauth 两个模块
from src.tuiwen.model.account import (AccountCreate, Account, AccountPublicCommon,
                                      AccountPasswordChange, AccountPasswordReset)
from src.tuiwen.model.oauth import (AccessToken, CodeVerify, RefreshToken,
                                    TurnstileVerifyToken, UpdateCredential)
# SCOPES_BASIC 已下沉到 core(原定义在 account/router.py, 属反向依赖)
from src.tuiwen.core import get_settings, SCOPES_BASIC
from src.tuiwen.dal.account import AccountDAO
from src.tuiwen.utils.jwt_token import generate_jwt_token, verify_jwt_token
from src.tuiwen.utils.redis_util import RedisKey, redis_get, redis_set, redis_delete
from src.tuiwen.utils.utils import validate_username, get_random_salt, hash_password

# 邮箱正则（通用标准正则，兼容绝大多数邮箱）
MAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


@dataclass
class AccountService:
    """账号业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_account_service 里是 AccountService(dao=dao))。
    """

    dao: AccountDAO

    # ---------------------------------------------------------
    # 注册
    # ---------------------------------------------------------
    async def register(self, dto: AccountCreate):
        """
        用户注册

        流程: 入参转模型 → 用户名兜底 → 唯一性查重 → 生成盐值并哈希密码 → 落库

        Args:
            dto: 注册入参(邮箱/账号ID/密码等)

        Returns:
            Account: 新建的账号 ORM 实例(尚未 commit)

        Raises:
            EmailAlreadyRegisteredError: 邮箱已被注册
            UsernameAlreadyUsedError: 账号ID已被占用
        """
        account_data = dto.model_dump()
        instance = Account(**account_data)

        # 用户名兜底
        if not instance.username:
            instance.username = instance.account_id

        # 查重
        exist_user = await self.dao.get_account_by_email_or_username(
            mail=instance.mail,
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
        # 每个账号独立随机盐, 避免彩虹表批量破解
        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=instance.password, salt=instance.salt)

        # 新增数据库记录
        # 注意：按照你的DAO规范，service层不做commit，commit交给上层/路由外层事务
        await self.dao.create(instance)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    # ---------------------------------------------------------
    # 查询 / 更新资料
    # ---------------------------------------------------------
    async def get_account(self, account_id: str):
        """按账户ID查询账号, 走唯一索引, 无匹配返回 None。"""
        return await self.dao.get_by_unique_field("account_id", account_id)

    async def update_account(self, account_id: str, account: AccountPublicCommon):
        """
        更新账号基本资料

        白名单式更新: 通过 forbidden_fields 排除所有敏感/系统字段,
        且仅取用户显式提交的字段(exclude_unset=True), 避免覆盖为空值。

        Args:
            account_id: 目标账户ID
            account: 待更新资料

        Returns:
            Account: 更新后的账号实例

        Raises:
            BizError: 账号不存在
        """
        instance = await self.dao.get_by_unique_field("account_id", account_id)
        if not instance:
            raise BizError(code=400, message="no such account")

        # 排除被更新字段
        forbidden_fields = {"account_id", "username", "mail", "mobile", "id", "password", "salt", "is_active",
                            "user_type", "im_id", "gmt_created", "gmt_modified"}

        account_data = account.model_dump(exclude_unset=True, exclude=forbidden_fields)
        instance.sqlmodel_update(account_data)

        return await self.dao.partial_update(instance.id, instance.model_dump())

    async def search(self, keyword: str, offset: int, limit: int):
        """
        按关键词模糊搜索账号(昵称或账号ID包含关键词, 不区分大小写)

        Args:
            keyword: 搜索关键词
            offset: 偏移量
            limit: 每页数量

        Returns:
            list[Account]: 匹配到的账号列表
        """
        cleaned = keyword.strip().lower()
        statement = select(Account).where(
            or_(Account.username.contains(cleaned), Account.nick_name.contains(cleaned))).offset(offset).limit(limit)

        # 交给基类统一执行: 自动选择读/主库 + 慢 SQL 埋点 + 异常日志
        return (await self.dao.exec_read(statement, "search_accounts")).all()

    # ---------------------------------------------------------
    # 验证码 / 密码
    # ---------------------------------------------------------
    async def account_send_code(self, data: Annotated[CodeVerify, "验证码信息"], ):
        """
        生成并缓存重置密码验证码, 返回发信所需上下文

        校验: 邮箱格式 → 用户是否存在 → 1 小时发送限流
        验证码随机 6 位数字, 写入 Redis 并设置过期时间。

        Args:
            data: 接收验证码的邮箱信息

        Returns:
            dict: {code, expire, to_mail}, 供后台任务发信使用

        Raises:
            BizError: 邮箱格式错误(400) / 用户不存在(404) / 发送过于频繁(400)
        """
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
        """
        忘记密码场景下的重置

        校验: 账号存在 → Redis 中的验证码非空且匹配
        校验通过后立刻删除验证码, 防止同一验证码被重复使用。

        Args:
            account: 重置入参(账号/验证码/新密码)

        Returns:
            Account: 更新后的账号实例

        Raises:
            BizError: 账号不存在(404) / 验证码过期未发送(404) / 验证码错误(400)
        """
        # account.username 语义是「用户名或邮箱」, 两个条件都要传, 否则少参直接 TypeError
        instance = await self.dao.get_account_by_email_or_username(mail=account.username, username=account.username)

        if not instance:
            raise BizError(code=404, message="no such account")

        # 按业界规范构造 key; 必须与发送验证码时(account_send_code 用客户端提交的 account 字段)
        # 使用同一个标识, 否则读到的 key 与写入的 key 不一致, 校验永远失败
        redis_key = RedisKey.reset_pwd_code(account.username)

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
        # 重置密码时同步换盐, 使旧密码哈希彻底失效
        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=account.password, salt=instance.salt)

        # 保存到数据库
        return await self.dao.partial_update(instance.id, instance.model_dump())

    # ---------------------------------------------------------
    # 认证 / 令牌
    # ---------------------------------------------------------
    async def authorize(self, username: str, password: str):
        """
        账号密码认证, 签发令牌对

        支持用户名或邮箱登录; 校验通过后签发:
            - refresh_token: 有效期取配置 REFRESH_TOKEN_EXPIRE_MINUTES, 用于换发 access_token
            - access_token : 携带 account_id / salt / scopes, 用于日常接口鉴权

        Args:
            username: 账号唯一标识(用户名或邮箱)
            password: 明文密码(内部会加盐哈希后比对)

        Returns:
            RefreshToken: 含 refresh_token / access_token / expires_in / account_id

        Raises:
            BizError: 凭据不匹配(400)
        """
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
        """
        用刷新令牌换发新的访问令牌

        会校验令牌类型必须为 refresh_token, 且令牌中的 account_id 必须与路径参数一致,
        防止跨账户使用他人令牌。

        Args:
            account_id: 路径中的账户ID
            refresh_token: 刷新令牌

        Returns:
            AccessToken: 新的访问令牌与账户ID

        Raises:
            BizError: 令牌非法/过期/跨账户(401)
        """
        try:
            payload = verify_jwt_token(data=refresh_token, grant_type='refresh_token')
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

    # ---------------------------------------------------------
    # 人机检测 / 用户名
    # ---------------------------------------------------------
    @classmethod
    async def two_step_verification(cls, data: Annotated[TurnstileVerifyToken, "人机监测的token"]):
        """
        调用 Cloudflare Turnstile siteverify 校验人机验证结果

        Args:
            data: 前端拿到的人机校验 token

        Returns:
            dict: {"success": bool}
        """
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
        """
        用户名可用性检测(先校验格式, 再查库)

        Args:
            username: 待检测用户名

        Returns:
            bool: True 表示已被占用

        Raises:
            BizError: 用户名格式不合法(400)
        """
        ok, detail = validate_username(username=username)
        if not ok:
            raise BizError(code=400, message=detail)

        is_exists = await self.dao.exists(username=username)
        return is_exists

    async def change_credential(self, account_id: str, data: Annotated[UpdateCredential, "更新用户认证信息"]):
        """
        修改用户认证信息

        当前仅支持修改 username: 校验格式 → 校验是否被占用 → 更新。
        账户ID 由令牌载荷提供, 不接受客户端传入。

        Args:
            account_id: 当前登录账户ID
            data: 变更入参(type + new_value)

        Returns:
            Account | None: 更新后的账号实例; 不支持的类型返回 None

        Raises:
            BizError: 用户名格式错误(400) / 用户名已被占用(400)
        """
        new_val = data.new_value.strip()

        if data.type == 'username':
            ok, desc = validate_username(new_val)
            if not ok: raise BizError(code=400, message=str(desc))

            is_exists = await self.dao.exists(username=data.new_value.strip().lower())
            if is_exists:
                raise BizError(code=400, message=str("该用户已被占用"))

            instance = await self.dao.get_by_unique_field("account_id", account_id)
            # 用户名统一小写存储, 避免大小写造成重复账号
            instance.username = new_val.strip().lower()

            return await self.dao.update(instance)
        return None

    async def change_password(self, account_id: str, salt, account: Annotated[AccountPasswordChange, '修改密码必要的参数']):
        """
        已登录状态下修改密码

        用令牌中的 salt 哈希原密码, 与库中记录比对通过后才允许修改;
        新密码不得与旧密码相同。修改成功后重新生成盐值。

        Args:
            account_id: 当前登录账户ID
            salt: 令牌载荷中的盐值
            account: 修改入参(原密码 + 新密码)

        Returns:
            Account: 更新后的账号实例

        Raises:
            BizError: 原密码错误(400) / 新旧密码相同(400)

        """
        try:
            instance = await self.dao.get_by_fields(account_id=account_id, password=hash_password(account.password_current, salt))
            if not instance:
                raise BizError(code=400, message="原密码不对,请重新输入原密码")
            assert account.password_new != instance.password, "新密码不能和旧密码相同"
        except AssertionError as e:
            raise BizError(code=400, message=str(e))

        instance.salt = get_random_salt(8)
        instance.password = hash_password(front_md5=account.password_new, salt=instance.salt)

        return await self.dao.update(instance)
