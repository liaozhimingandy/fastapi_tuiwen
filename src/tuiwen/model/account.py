#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: FastAPIDemo
    @File： account.py
    @Author：liaozhimingandy
    @mail: liaozhimingandy@gmail.com
    @Date：2025/1/19 09:19
    @Desc: 账户模型: 注册入参 / 数据库表 / 公开信息 / 密码相关模型
=================================================
"""
import uuid
from datetime import datetime, timezone, date
from enum import IntEnum
from typing import Optional

from pydantic import AliasChoices, EmailStr, field_validator, field_serializer
from sqlalchemy import SMALLINT, Column, JSON, BigInteger, Identity, func, UUID
from sqlmodel import SQLModel, Field, text

from src.tuiwen.model.types import IntEnumType, UTCDateTime

from src.tuiwen.core import get_settings
from src.tuiwen.utils.datetime_utils import to_utc, utcnow
from src.tuiwen.utils import get_random_salt

TABLE_PREFIX = get_settings().TABLE_PREFIX


def uuid_generator(size: int = 7):
    """生成指定长度的十六进制随机串(取 uuid4 前 size 位)。"""
    return uuid.uuid4().hex[:size]


def salt_default():
    """盐默认生成"""
    return get_random_salt(6)


def app_id_default():
    """应用id随机生成"""
    return uuid_generator(5)


class SexEnum(IntEnum):
    """性别枚举, 取值沿用 GB/T 2261.1(0未知 1男 2女 9未说明)。"""
    UnKnown = 0
    Male = 1
    Female = 2
    Other = 9

    @property
    def label(self):
        mapping = {
            0: "未知的性别",
            1: "男性",
            2: "女性",
            9: "未说明的性别"
        }
        return mapping[self.value]


class AccountPublicCommon(SQLModel):
    """账户公共字段DTO：用户名/昵称/性别/头像/简介，供注册入参和公开信息模型继承"""
    username: Optional[str] = Field(None, max_length=32, description="用户名")
    nickname: Optional[str] = Field(None, max_length=30, description="昵称")
    birthday: Optional[date] = Field(None, description="出生日期")
    area_code: str = Field(default="CHN", max_length=3, description="区域代码")
    sex: SexEnum = Field(default=SexEnum.UnKnown, ge=0, description="性别")
    avatar: Optional[str] = Field(None, max_length=200, description="头像链接")
    bio: Optional[str] = Field(None, max_length=256, description="用户自我简介")


class AccountLogin(SQLModel):
    """登录字段: 邮箱 + 密码(前端已 MD5, 固定 32 位)。"""
    mail: EmailStr | None = Field(None, index=True, max_length=64, description='电子邮箱')
    password: str = Field(..., max_length=32, min_length=32, description='用户密码')


class AccountCreate(AccountPublicCommon, AccountLogin):
    """注册入参模型 = 公开字段 + 登录字段(username 由后端按邮箱生成, 前端不必传)。"""
    pass


class AccountInfo(AccountPublicCommon):
    """账号信息响应模型(不含密码/盐), api/account.py 各接口的 response_model。

    继承 SQLModel 自带 from_attributes, 可直接从 ORM 实例(Account)转换;
    比 AccountPublicCommon 多暴露 id/mail/mobile 与三个状态开关, 仍不包含 password/salt。
    """
    id: uuid.UUID = Field(..., description="用户ID (uuid7)", serialization_alias="account_id",
                          validation_alias=AliasChoices("id", "account_id"))
    mail: Optional[EmailStr] = Field(None, max_length=64, description="电子邮箱")
    mobile: Optional[str] = Field(None, max_length=32, description="电话号码")
    # 三列在库里都是 NOT NULL DEFAULT true, 这里保持非 Optional ——
    # 若旧库存在 NULL, 响应校验会直接 500, 需要先把历史数据刷成 true
    is_active: bool = Field(default=True, description="账户状态")
    allow_beep: bool = Field(default=True, description="是否允许提示音")
    allow_vibration: bool = Field(default=True, description="是否允许震动提示")


class Account(SQLModel, table=True):
    """账户数据库表模型(tw_account)。

    NOTE: 基类必须是 SQLModel —— SQLModel 的元类靠它接管 Pydantic 校验与建表,
          换成 pydantic.BaseModel 会在定义 `table=True` 时直接抛
          `TypeError: Account.__init_subclass__() takes no keyword arguments`

    - password: 前端 MD5 + 盐后再 SHA256 的 64 位摘要, 明文与前端 MD5 都不落库
    - salt: 每账号独立随机盐, 重置密码时同步更换
    - extra: JSON, 存用户个性化配置
    - im_id: IM 系统的用户标识
    """

    __tablename__ = f"{TABLE_PREFIX}account"  # 表名
    __table_args__ = {'comment': '账户信息'}  # 表备注

    # 主键即业务账户 ID: DB 列名为 id, 对外 JSON 仍沿用 account_id(兼容既有客户端)
    id: uuid.UUID = Field(
        default_factory=uuid.uuid7,
        primary_key=True,
        sa_type=UUID,
        sa_column_kwargs={"comment": "表主键ID (uuid7)", "server_default": text("uuidv7()")},
        serialization_alias="account_id",
        validation_alias=AliasChoices("id", "account_id"),
    )
    # username/password/salt 在 Service 落库前一定会被赋值, 但 Python 侧允许为 None
    # (注册时先构造实例, 再用主键 hex 兜底 username), 因此注解写成可选, 不要写
    # `str` + `Field(None)` 这种"类型非空却默认 None"的自相矛盾写法
    username: str | None = Field(None, index=True, max_length=32, description='用户名',
                                 sa_column_kwargs={'comment': '用户名'}, unique=True)
    nickname: str | None = Field(None, max_length=30, description='昵称', sa_column_kwargs={'comment': '昵称'})
    mail: EmailStr | None = Field(None, index=True, max_length=64, description='电子邮箱',
                                  sa_column_kwargs={'comment': '电子邮箱'}, unique=True)
    mobile: str | None = Field(None, index=True, max_length=32, description='电话号码',
                               sa_column_kwargs={'comment': '电话号码'}, unique=True)
    birthday: date | None = Field(None, description='出生日期', sa_column_kwargs={'comment': '出生日期'})
    area_code: str = Field(default='CHN', max_length=3, description='区域代码',
                           sa_column_kwargs={'comment': '区域代码'})
    sex: SexEnum = Field(default=SexEnum.UnKnown, sa_type=IntEnumType(SexEnum), ge=0, description='性别',
                         sa_column_kwargs={'comment': '性别'})
    avatar: str | None = Field(None, max_length=200, description='头像链接', sa_column_kwargs={'comment': '头像链接'})
    bio: str | None = Field(None, max_length=256, description='用户自我简介',
                            sa_column_kwargs={'comment': '用户自我简介'})
    user_type: int = Field(default=1, sa_type=SMALLINT, ge=1, description='账户类型',
                           sa_column_kwargs={'comment': '账户类型'})
    password: str | None = Field(None, max_length=64, min_length=64, description='用户密码;经过MD5计算加密',
                                 sa_column_kwargs={'comment': '用户密码'})
    salt: str | None = Field(default=None, max_length=8, description='盐', sa_column_kwargs={'comment': '盐'})
    allow_add_friend: bool | None = Field(default=True, description='允许添加好友',
                                          sa_column_kwargs={'comment': '允许添加好友'})
    im_id: str | None = Field(None, max_length=64, description='im ID', sa_column_kwargs={'comment': 'im ID'},
                              unique=True, index=True)
    # 可变默认值必须用 default_factory, 否则所有实例共享同一个 dict
    extra: dict | None = Field(default_factory=dict, description='个性化配置信息', max_length=1024,
                               sa_column_kwargs={'comment': '存储用户自定义配置信息'},
                               sa_type=JSON)
    # 三列都用 bool(非空) + server_default: 语义上账户要么启用要么停用, 不存在"未知"
    is_active: bool = Field(default=True, description='账户状态',
                            sa_column_kwargs={'comment': '账户状态', 'server_default': text("true")})
    allow_beep: bool = Field(default=True, description='是否允许提示音',
                             sa_column_kwargs={'comment': '是否允许提示音', 'server_default': text("true")})
    allow_vibration: bool = Field(default=True, description='是否允许震动提示',
                                  sa_column_kwargs={'comment': '是否允许震动提示', 'server_default': text("true")})

    created_at: datetime = Field(..., default_factory=utcnow, description='创建日期时间',
                                sa_column=Column(UTCDateTime, default=utcnow,
                                                 comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                )
    updated_at: datetime = Field(..., default_factory=utcnow, description="最后更新时间",
                                sa_column=Column(
                                    UTCDateTime,
                                    server_default=func.now(),
                                    onupdate=func.now(),
                                    nullable=False,
                                    comment="最后更新时间"
                                ))

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value):
        return to_utc(value)

    @field_validator("username", "mail", mode="before")
    def username_to_lower(cls, v: Optional[str]) -> Optional[str]:
        """落库前把用户名/邮箱统一转小写并去首尾空白。

        NOTE: 邮箱也必须归一 —— 注册查重是 case-insensitive 的, 而登录按 mail 精确匹配,
              大小写不一致会导致"注册成功但登录不上"。
        """
        if v is None:
            return None
        return v.strip().lower()


class AccountPasswordReset(SQLModel):
    """找回密码入参: 用户名或邮箱 + 新密码 + 邮箱验证码(6 位)。"""
    username: str = Field(..., description='用户名或者邮箱')
    password: str = Field(..., max_length=32, min_length=32, description='用户密码')
    code: str = Field(..., max_length=6, min_length=6, description="验证码")


class AccountPasswordChange(SQLModel):
    """已登录用户修改密码入参: 校验当前密码后换新。

    NOTE: 当前登录账户ID 由令牌载荷(request.state.account_id)提供, 不在此 DTO 中透传,
          避免客户端伪造越权; 因此本模型不含 id 字段。
    """
    password_current: str = Field(..., max_length=32, min_length=32, description='当前用户密码')
    password_new: str = Field(..., max_length=36, min_length=32, description='用户新密码')


class App(SQLModel, table=False):
    """
    应用模型
    示例: 小程序,公众号...

    NOTE: table=False —— 只声明结构不建表, 目前也无对应 DAO;
          app_secret 以明文存储且无加密, 对外提供前建议做哈希/加密
    """

    __tablename__ = f"{TABLE_PREFIX}app"  # 表名
    __table_args__ = {'comment': '应用'}  # 表备注

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'},
                    sa_type=BigInteger)
    app_id: str = Field(default=app_id_default, index=True, max_length=7, unique=True,
                        description='appid', sa_column_kwargs={'comment': 'appid'})
    app_secret: str = Field(..., max_length=32, description='应用密钥', sa_column_kwargs={'comment': '应用密钥'})
    salt: str = Field(default=salt_default, max_length=8, description='盐',
                      sa_column_kwargs={'comment': '盐'})
    app_name: str = Field(..., max_length=32, description='应用名称', sa_column_kwargs={'comment': '应用名称'})
    app_en_name: str | None = Field(None, max_length=64, description='应用英文名称',
                                    sa_column_kwargs={'comment': '应用英文名称'})
    is_active: bool = Field(default=True, description='激活状态', sa_column_kwargs={'comment': '激活状态'})
    created_at: datetime = Field(..., default_factory=utcnow, description='创建日期时间',
                                sa_column=Column(UTCDateTime, default=utcnow,
                                                 comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                )
    updated_at: datetime = Field(..., default_factory=utcnow, description='最后修改时间',
                                sa_column=Column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                 comment='最后修改时间')
                                )

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value):
        return to_utc(value)
