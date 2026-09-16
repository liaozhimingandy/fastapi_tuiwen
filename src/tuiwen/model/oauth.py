"""OAuth/令牌与验证码模型: token 响应结构、验证码发送入参、凭据更新入参。

不映射数据库表, 仅做请求/响应的数据校验载体。
"""
from datetime import timedelta
from enum import Enum
from typing import Literal, Optional

from pydantic import field_validator
from sqlmodel import SQLModel, Field

from src.tuiwen.core import get_settings

TABLE_PREFIX = get_settings().TABLE_PREFIX

########################################################################################################################
# token
class Token(SQLModel):
    expires_in: int = Field(default=int(timedelta(days=1).total_seconds()), description="过期时间,单位为秒")
    token_type: str = Field(default='Bearer', description="令牌类型")
    scopes: str = Field(default='basic', description="权限范围")
    access_token: str = Field(..., description="请求令牌")

class AccessToken(Token):
    """访问令牌: 在基础字段上补充账户ID。"""
    account_id: str = Field(..., description="账户ID")

class RefreshToken(AccessToken):
    """刷新令牌: 携带 refresh_token 字段, 用于换取新的 access_token。"""
    refresh_token: str = Field(..., description="刷新令牌")

class AppAccessToken(Token):
    """应用级访问令牌(小程序/服务端应用), 携带 app_id。"""
    app_id: str = Field(..., description="应用ID")

class AppRefreshToken(AppAccessToken):
    """应用级刷新令牌。"""
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
    type: username / mail / mobile
    new_value: 新值
    password: 修改邮箱、手机号必填；修改用户名不需要传
    code: 修改邮箱、手机号必填；用户名不需要
    """
    type: Literal["username", "mail", "mobile"]
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