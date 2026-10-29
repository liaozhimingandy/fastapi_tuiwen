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
    1. HTTP 相关处理 —— BizError 由 API 层转换为 HTTPException

事务说明:
    本层的写方法(register/reset_password/change_password/change_credential/update_account)
    在 DAO flush 之后自行 commit, 保证调用方拿到的是真正落库的数据;
    ⚠️ 部分 API 在调用本层之后又调了一次 dao.commit(), 属重复提交(第二次提交的是空事务),
       不会出错但多一次往返, 清理时可以统一收敛到一侧

分层位置:
    API → AccountService → AccountDAO → PostgreSQL (Redis 存验证码 / SMTP 发信)
"""
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

import httpx

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.common.exceptions import EmailAlreadyRegisteredError, UsernameAlreadyUsedError
# 模型统一从 model 包绝对导入(原 "from model.account" 是裸导入, 只在把 src/tuiwen 也加入
# sys.path 时才成立, 与项目「唯一源根=项目根」的约定冲突);
# 重构后账户字段与令牌/验证码模型分别位于 account / oauth 两个模块
from src.tuiwen.model.account import (AccountCreate, Account, AccountInfo, AccountPublicCommon,
                                      AccountPasswordChange, AccountPasswordReset)
from src.tuiwen.model.follow import FollowCountModel
from src.tuiwen.model.oauth import (AccessToken, CodeVerify, RefreshToken,
                                    TurnstileVerifyToken, UpdateCredential)
# SCOPES_BASIC 已下沉到 core(原定义在 account/router.py, 属反向依赖)
from src.tuiwen.core import get_settings, SCOPES_BASIC
from src.tuiwen.dal.account import AccountDAO
from src.tuiwen.dal.follow import FollowDAO
from src.tuiwen.dal.like import LikeDAO
from src.tuiwen.utils.jwt_token import generate_jwt_token, verify_jwt_token
from src.tuiwen.utils.redis_util import RedisKey, redis_get, redis_set, redis_delete
from src.tuiwen.utils.utils import validate_username, get_random_salt, hash_password

# 邮箱正则（通用标准正则，兼容绝大多数邮箱）
MAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


@dataclass
class AccountService:
    """账号业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_account_service 里是 AccountService(dao=dao, follow_dao=follow_dao, like_dao=like_dao))。

    follow_dao/like_dao 用于搜索结果批量装配关注统计; 为 None 时不装配(旧调用方兼容)。
    """

    dao: AccountDAO
    follow_dao: FollowDAO | None = None
    like_dao: LikeDAO | None = None

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

        # 用户名兜底: 用主键的 32 位十六进制形式(去掉连字符), 与 username 列 varchar(32) 对齐
        if not instance.username:
            instance.username = instance.id.hex

        # 用户名黑名单正则校验
        ok, detail = validate_username(instance.username)
        if not ok:
            raise BizError(code=400, message=detail)

        # 查重
        exist_user = await self.dao.get_account_by_email_or_username(
            mail=instance.mail,
            username=instance.username
        )

        if exist_user:
            # 区分冲突字段抛出不同提示
            # mail 允许为空(AccountLogin.mail 是可选字段), 命中账号可能没填邮箱,
            # 直接 .lower() 会 AttributeError; 用假值兜底再比较
            if (exist_user.mail or "").lower() == (instance.mail or "").lower() and instance.mail:
                raise EmailAlreadyRegisteredError(
                    code=400,
                    message="该邮箱已被注册,如您是账号所有者,请直接登录"
                )
            if (exist_user.username or "").lower() == (instance.username or "").lower():
                raise UsernameAlreadyUsedError(
                    code=400,
                    message="该账号ID已被占用，请更换后重试"
                )

        # 更新用户信息
        # 每个账号独立随机盐, 避免彩虹表批量破解
        instance.salt = get_random_salt(6)
        instance.password = hash_password(front_md5=instance.password, salt=instance.salt)

        # 新增数据库记录
        await self.dao.create(instance)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    # ---------------------------------------------------------
    # 查询 / 更新资料
    # ---------------------------------------------------------
    async def get_account(self, account_id: uuid.UUID):
        """按账户主键ID查询账号, 走主键, 无匹配返回 None。"""
        return await self.dao.get_by_unique_field("id", account_id)

    async def update_account(self, account_id: uuid.UUID, account: AccountPublicCommon):
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
        instance = await self.dao.get_by_unique_field("id", account_id)
        if not instance:
            raise BizError(code=400, message="no such account")

        # 排除被更新字段
        forbidden_fields = {"account_id", "username", "mail", "mobile", "id", "password", "salt", "is_active",
                            "user_type", "im_id", "created_at", "updated_at"}

        account_data = account.model_dump(exclude_unset=True, exclude=forbidden_fields)
        instance = await self.dao.partial_update(instance.id, account_data)
        await self.dao.write_db.commit()
        return instance

    async def search(self, keyword: str, offset: int, limit: int,
                     viewer_id: uuid.UUID | None = None):
        """
        按关键词模糊搜索账号(昵称或账号ID包含关键词, 不区分大小写)

        viewer_id 传入时批量装配关注统计(follow 字段: 粉丝数/关注数/是否已关注/获赞数),
        供搜索结果列表直接渲染「关注」按钮, 省去前端逐个调 /follows/{id}/count/。

        Args:
            keyword: 搜索关键词
            offset: 偏移量
            limit: 每页数量
            viewer_id: 当前登录账户ID; None 时不装配关注统计(匿名)

        Returns:
            list[Account]: 匹配到的账号列表(follow 字段视 viewer 而定)
        """
        dataset = await self.dao.search(keyword=keyword, offset=offset, limit=limit)
        if not dataset:
            return []
        # follow_dao 未注入或匿名时不装配 —— 统一转成 AccountInfo(follow=None),
        # 不直接返回 Account ORM 实例(它没有 follow 属性, 访问会 AttributeError)
        if self.follow_dao is None or viewer_id is None:
            return [AccountInfo.model_validate(a.model_dump()) for a in dataset]
        return await self._attach_follow_info(dataset, viewer_id)

    async def _attach_follow_info(self, accounts, viewer_id: uuid.UUID):
        """批量装配关注统计(3 条聚合查询, 不随结果条数增长)

        口径与 FollowService.get_follow_info_by_id 一致:
        follower_count/followee_count/is_following/like_count(该作者帖子的获赞数)。
        """
        ids = [a.id for a in accounts]
        counts = await self.follow_dao.counts_by_targets(ids)
        liked = await self.like_dao.count_likes_by_authors(ids) if self.like_dao else {}
        followed = await self.follow_dao.followed_account_ids(viewer_id, ids)

        result = []
        for a in accounts:
            # NOTE: 不能用 model_validate(a)(from_attributes 直读 ORM)——
            #       Account 表模型没有 follow 属性, 校验时 getattr 失败且不会回退到默认值;
            #       先 dump 成 dict 再验证, follow 字段才能落到默认 None
            info = AccountInfo.model_validate(a.model_dump())
            stat = counts.get(a.id, {"follower_count": 0, "followee_count": 0})
            info.follow = FollowCountModel(
                follower_count=int(stat["follower_count"]),
                followee_count=int(stat["followee_count"]),
                is_following=a.id in followed,
                like_count=int(liked.get(a.id, 0)),
            )
            result.append(info)
        return result

    # ---------------------------------------------------------
    # 验证码 / 密码
    # ---------------------------------------------------------
    async def account_send_code(self, data: Annotated[CodeVerify, "验证码信息"], ):
        """
        生成并缓存重置密码验证码, 返回发信所需上下文

        校验: 邮箱格式 → 用户是否存在 → 发送限流(与验证码 TTL 同为 REDIS_EXPIRE, 默认 30 分钟)
        验证码随机 6 位数字(用 secrets 生成, 不用 random —— 后者是可预测的伪随机序列),
        写入 Redis 并设置过期时间。

        Args:
            data: 接收验证码的邮箱信息

        Returns:
            dict: {code, expire, to_mail}, 供后台任务发信使用

        Raises:
            BizError: 邮箱格式错误(400) / 用户不存在(404) / 发送过于频繁(400)
        """
        # send_notification
        code = data.model_dump(exclude={'code'})
        instance_code = CodeVerify(**code, code="".join(secrets.choice("0123456789") for _ in range(6)))
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
        # 发送限流(与验证码同为 REDIS_EXPIRE, 默认 30 分钟)
        # ======================
        # key 用查到的账户ID而不是客户端提交的字符串:
        # 用户申请验证码时填邮箱、重置时填用户名也应当能对上, 用提交值做 key 会错位
        key = RedisKey.reset_pwd_code(str(instance.id))
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

        # 用账户ID构造 key —— 必须与 account_send_code 侧完全一致。
        # 两边都用查到的账户ID, 用户"用邮箱收码、用用户名重置"(或大小写不一致)才能校验通过;
        # 若改用提交值, 两侧字符串不同就会读到空值, 表现为"验证码已过期或未发送"
        redis_key = RedisKey.reset_pwd_code(str(instance.id))

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
        new_salt = get_random_salt(6)
        new_password = hash_password(front_md5=account.password,salt=new_salt,)
        instance = await self.dao.partial_update(
            instance.id,
            {
                "salt": new_salt,
                "password": new_password,
            },
        )
        # 保存到数据库
        await self.dao.write_db.commit()
        return instance

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
            assert instance.is_active is True, '账号已经禁用'
        except AssertionError as e:
            raise BizError(code=400, message=str(e))


        data = {"account_id": str(instance.id), "salt": instance.salt, 'scopes': SCOPES_BASIC}
        refresh_token = generate_jwt_token(data,
                                           expires_in=timedelta(minutes=get_settings().REFRESH_TOKEN_EXPIRE_MINUTES),
                                           grant_type="refresh_token")

        data.update(**{'jwt_account_id': str(instance.id)})
        access_token = generate_jwt_token(data, grant_type="access_token")

        return RefreshToken(refresh_token=refresh_token, access_token=access_token,
                            expires_in=int(
                                timedelta(minutes=get_settings().REFRESH_TOKEN_EXPIRE_MINUTES).total_seconds()),
                            account_id=str(instance.id))

    @classmethod
    async def refresh_token(cls, account_id: uuid.UUID, refresh_token: str):
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
            assert str(account_id) == payload.get('account_id'), '请检查token是否为该账户的token同时为刷新令牌,请不要跨账户操作'
        except AssertionError as e:
            raise BizError(code=401, message=str(e))
        except Exception as e:
            raise BizError(code=401, message=str(e))

        data = {"account_id": str(account_id), "salt": payload.get('salt'), 'jwt_account_id': str(account_id),
                'scopes': SCOPES_BASIC}

        access_token = generate_jwt_token(data, grant_type="access_token",
                                          expires_in=timedelta(minutes=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES))

        return AccessToken(access_token=access_token, account_id=str(account_id))

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

    async def change_credential(self, account_id: uuid.UUID, data: Annotated[UpdateCredential, "更新用户认证信息"]):
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

            instance = await self.dao.get_by_unique_field("id", account_id)
            # 用户名统一小写存储, 避免大小写造成重复账号
            # 用 partial_update(Core UPDATE) 而不是 dao.update() 整对象覆盖, 原因有二:
            #   1. dao.update() 内部走 write_db.merge(), merge 会把所有列(含 updated_at 的旧值)
            #      一并写进 SET, 列的 onupdate=func.now() 因此不触发, updated_at 不会刷新;
            #   2. 只更新 username 一列, 也与本服务其它更新路径(update_account /
            #      reset_password / change_password)的写法保持一致。
            # 原实现写的是 `instance.created_at = datetime.now(UTC)`: 既改错了字段
            # (覆盖了创建时间, 且 updated_at 反而不动), 又是应用时钟, 与 DB 时钟口径不一致
            instance = await self.dao.partial_update(
                instance.id, {"username": new_val.strip().lower()}
            )
            await self.dao.write_db.commit()
            return instance

        return None

    async def change_password(self, account_id: uuid.UUID, salt,
                              account: Annotated[AccountPasswordChange, '修改密码必要的参数']):
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
        # 先按令牌里的盐算出原密码摘要, 与库中摘要做等值比较(库里存的是加盐 SHA256)
        current_hash = hash_password(account.password_current, salt)
        instance = await self.dao.get_by_fields(id=account_id, password=current_hash)
        if not instance:
            raise BizError(code=400, message="原密码不对,请重新输入原密码")

        # 新旧是否相同的判定必须"同盐比同盐":
        #   入参是明文 MD5、库中是加盐摘要, 直接比较永远不等(原实现的 assert 形同虚设);
        #   而用了新盐去算摘要, 盐不同摘要必然不同, 同样比不出来 —— 必须用旧盐重算新密码
        if hash_password(account.password_new, instance.salt) == instance.password:
            raise BizError(code=400, message="新密码不能和旧密码相同")

        new_salt = get_random_salt(6)
        # 落库的是"新密码 + 新盐"的摘要; 原实现写的是 account.password, 而
        # AccountPasswordChange 只有 password_current / password_new 两个字段, 会 AttributeError
        new_password = hash_password(front_md5=account.password_new, salt=new_salt,)
        instance = await self.dao.partial_update(
            instance.id,
            {
                "salt": new_salt,
                "password": new_password,
            },
        )
        await self.dao.write_db.commit()
        return instance
