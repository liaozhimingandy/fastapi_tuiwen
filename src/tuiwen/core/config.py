import os
from enum import Enum
from functools import lru_cache
from typing import Any, Annotated, Optional

from pydantic import computed_field, BeforeValidator, Field, model_validator
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings

from ..utils.logger import logger

def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    TABLE_PREFIX: str = Field("tw_", description="table prefix")
    DEBUG: bool = Field(True, description="debug mode")
    ACCOUNT_ID_PREFIX: str = Field("twid_", description="account id prefix")
    # SECRET_KEY: str = secrets.token_urlsafe(16)
    SECRET_KEY: str = 'tw-insecure-5xlvJWvZ_TOiJzKvtpTuBMfllIJ1WE7gvODgA41dvnA'
    STATIC_URL: str = Field("static/", description="static url")
    ALLOWED_IMAGE_FORMATS: str = Field("jpg,jpeg,png", description="allowed image formats")
    POSTGRES_HOST: str = Field("postgresql", description="postgres server")
    POSTGRES_PORT: int = Field(5432, description="postgres port")
    POSTGRES_USER: str = Field("postgres", description="postgres user")
    POSTGRES_PASSWORD: Optional[str] = Field(
        default=None,
        validate_default=True,  # 确保验证器始终执行
        description="密码将从文件读取（非环境变量）"
    )
    POSTGRES_PASSWORD_FILE: Optional[str] = Field(
        default=None,
        description="密码文件路径（如 /run/secrets/postgres_password.txt）"
    )
    POSTGRES_DB: str = Field("localhost", description="postgres database")
    TIME_ZONE: str = Field("Asia/Shanghai", description="time zone")
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 28, description="refresh token expire minutes")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 1, description="access token expire minutes")

    BACKEND_CORS_ORIGINS: Annotated[
        list[str] | str, BeforeValidator(parse_cors)
    ]

    class Config:
        # 默认从.env文件加载
        env_file = ".env" if not os.getenv("DOCKER_MODE") else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> MultiHostUrl:
        return MultiHostUrl.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @model_validator(mode='after')
    def load_password_from_file(self):
        try:
            with open(self.POSTGRES_PASSWORD_FILE, 'r') as f:
                self.POSTGRES_PASSWORD = f.read().strip()
        except Exception as e:
            logger.error(e)
            raise ValueError(
                f"密码文件读取失败: {self.POSTGRES_PASSWORD_FILE} | "
                f"错误: {str(e)} | "
                f"权限: {oct(os.stat(self.POSTGRES_PASSWORD_FILE).st_mode)[-3:] if os.path.exists(self.POSTGRES_PASSWORD_FILE) else 'N/A'}")

        return self

class Tag(Enum):
    account = 'account'
    post = 'post'
    like = 'like'
    comment = 'comment'
    log = 'log'
    oauth = 'oauth'
    app = 'app'
    upload = 'upload'
    notifications = 'notifications'


@lru_cache
def get_settings():
    return Settings()
