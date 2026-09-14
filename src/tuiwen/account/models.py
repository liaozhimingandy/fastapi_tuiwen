#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: FastAPIDemo
    @File： models.py
    @Author：liaozhimingandy
    @mail: liaozhimingandy@gmail.com
    @Date：2025/1/19 09:19
    @Desc: 
=================================================
"""
import os, uuid
from datetime import datetime, timedelta, timezone, date
from enum import Enum, IntEnum
from typing import Literal, Optional

from pydantic import EmailStr, field_validator, field_serializer
from sqlalchemy import DateTime, SMALLINT, Column, JSON, BigInteger, Identity
from sqlmodel import SQLModel, Field, text

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


def uuid_generator(size: int = 7):
    return uuid.uuid4().hex[:size]


def salt_default():
    """盐默认生成"""
    return uuid_generator(8)


def userid_default():
    """用户id随机生成"""
    return f'{os.getenv("PREFIX_ID", "twid_")}{uuid_generator(7)}'


def app_id_default():
    """应用id随机生成"""
    return uuid_generator(5)


class AccountPublicCommon(SQLModel):

    class SexEnum(IntEnum):
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

    username: str | None = Field(None, index=True, max_length=32, description='用户名',
                                 sa_column_kwargs={'comment': '用户名'}, unique=True)
    nick_name: str | None = Field(None, max_length=30, description='昵称', sa_column_kwargs={'comment': '昵称'})
    gmt_birth: date | None = Field(None, description='出生日期', sa_column_kwargs={'comment': '出生日期'})
    area_code: str = Field(default='CHN', max_length=3, description='区域代码', sa_column_kwargs={'comment': '区域代码'})
    sex: SexEnum = Field(default=SexEnum.UnKnown, sa_type=SMALLINT, ge=0, description='性别',sa_column_kwargs={'comment': '性别'})
    avatar: str | None = Field(None, max_length=200, description='头像链接', sa_column_kwargs={'comment': '头像链接'})
    bio: str | None = Field(None, max_length=256, description='用户自我简介', sa_column_kwargs={'comment': '用户自我简介'})

    @field_validator("username", mode="before")
    def username_to_lower(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().lower()

class AccountLogin(SQLModel):
    mail: EmailStr | None = Field(None, index=True, max_length=64, description='电子邮箱',
                              sa_column_kwargs={'comment': '电子邮箱'}, unique=True)
    password: str  = Field(..., max_length=32, min_length=32, description='用户密码', sa_column_kwargs={'comment': '用户密码'})


class AccountCreate(AccountPublicCommon, AccountLogin):
    pass


class AccountBase(AccountPublicCommon):
    """
    账户信息模型
    """
    account_id: str = Field(..., default_factory=userid_default, index=True, max_length=32,
                            description='用户ID', sa_column_kwargs={'comment': '用户ID'}, unique=True)
    mail: EmailStr | None = Field(None, index=True, max_length=64, description='电子邮箱',
                              sa_column_kwargs={'comment': '电子邮箱'}, unique=True)
    mobile: str | None = Field(None, index=True, max_length=32, description='电话号码',
                               sa_column_kwargs={'comment': '电话号码'}, unique=True)
    is_active: bool | None = Field(default=True, description='账户状态', sa_column_kwargs={'comment': '账户状态'})
    allow_beep: bool | None = Field(default=True, description='是否允许提示音',
                                    sa_column_kwargs={'comment': '是否允许提示音'})
    allow_vibration: bool | None  = Field(default=True, description='是否允许震动提示',
                                  sa_column_kwargs={'comment': '是否允许震动提示'})

    @field_validator("mail", mode="before")
    def username_to_lower(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip().lower()


class Account(AccountBase, table=True):

    __tablename__ = f"{TABLE_PREFIX}account"  # 表名
    __table_args__ = {'comment': '账户信息'}  # 表备注

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    user_type: int = Field(default=1, sa_type=SMALLINT, ge=1, description='账户类型',
                                  sa_column_kwargs={'comment': '账户类型'})
    password: str = Field(None, max_length=64, min_length=64, description='用户密码;经过MD5计算加密', sa_column_kwargs={'comment': '用户密码'})
    salt: str = Field(default=None, max_length=8, description='盐', sa_column_kwargs={'comment': '盐'})
    allow_add_friend: bool | None = Field(default=True, description='允许添加好友',
                                          sa_column_kwargs={'comment': '允许添加好友'})
    im_id: str | None = Field(None, max_length=64, description='im ID', sa_column_kwargs={'comment': 'im ID'},
                              unique=True, index=True)
    extra: dict | None = Field(default={}, description='个性化配置信息', max_length=1024,
                               sa_column_kwargs={'comment': '存储用户自定义配置信息'},
                               sa_type=JSON)
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                  )
    update_at: datetime = Field(..., default_factory=lambda: datetime.now(timezone.utc), description='最后修改时间',
                                   sa_column=Column(DateTime(timezone=True), default=datetime.now, onupdate=datetime.now, comment='最后修改时间')
                                   )

    @field_serializer('create_at', 'update_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class AccountPublic(AccountBase):
    pass

class AccountPasswordReset(SQLModel):
    username: str = Field(..., description='用户名或者邮箱')
    password: str = Field(..., max_length=32, min_length=32, description='用户密码')
    code: str = Field(..., max_length=6, min_length=6, description="验证码")


class AccountPasswordChange(SQLModel):
    account_id: str = Field(..., description='用户ID')
    password_current: str = Field(..., max_length=32, min_length=32, description='当前用户密码')
    password_new: str = Field(..., max_length=36, min_length=32, description='用户新密码')


class App(SQLModel, table=False):
    """
    应用模型
    示例: 小程序,公众号...
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
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                  )
    update_at: datetime = Field(..., default_factory=lambda: datetime.now(timezone.utc), description='最后修改时间',
                                   sa_column=Column(DateTime(timezone=True), default=datetime.now, onupdate=datetime.now, comment='最后修改时间')
                                   )

    @field_serializer('create_at', 'update_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)

########################################################################################################################
# token
class Token(SQLModel):
    expires_in: int = Field(default=int(timedelta(days=1).total_seconds()), description="过期时间,单位为秒")
    token_type: str = Field(default='Bearer', description="令牌类型")
    scopes: str = Field(default='basic', description="权限范围")
    access_token: str = Field(..., description="请求令牌")

class AccessToken(Token):
    account_id: str = Field(..., description="账户ID")

class RefreshToken(AccessToken):
    refresh_token: str = Field(..., description="刷新令牌")

class AppAccessToken(Token):
    app_id: str = Field(..., description="账户ID")

class AppRefreshToken(AppAccessToken):
    refresh_token: str = Field(..., description="刷新令牌")

########################################################################################################################
# 验证码
########################################################################################################################
class CodeChannel(str, Enum):
    SMS = "sms"
    MAIL = "mail"


class CodeScene(str, Enum):
    LOGIN = "login"
    REGISTER = "register"
    RESET_PWD = "reset_pwd"
    BIND = "bind"

class CodeVerify(SQLModel):
    channel: CodeChannel = Field(..., description="渠道")
    account: str = Field(..., description="手机号或邮箱")
    scene: CodeScene = Field(..., description="场景")
    code: str | None = Field(None, min_length=4, max_length=6, description="验证码")

class TurnstileVerifyToken(SQLModel):
    cf_turnstile_token: str


class UpdateCredential(SQLModel):
    """
    type: username / mail / phone
    new_value: 新值
    password: 修改邮箱、手机号必填；修改用户名不需要传
    code: 修改邮箱、手机号必填；用户名不需要
    """
    type: Literal["username", "mail", "phone"]
    new_value: str
    password: Optional[str] = None
    code: Optional[str] = None

    @field_validator("password")
    def check_password_required(cls, v, values):
        t = values.data.get("type")
        if t in ("mail", "mobile"):
            if not v or len(v.strip()) == 0:
                raise ValueError("修改邮箱、手机号必须输入当前密码")
        return v

    @field_validator("code")
    def check_code_required(cls, v, values):
        t = values.data.get("type")
        if t in ("mail", "mobile"):
            if not v or len(v.strip()) == 0:
                raise ValueError("修改邮箱、手机号必须传入验证码code")
        # 修改用户名时，即使前端传了code也清空
        if t == "username":
            return None
        return v