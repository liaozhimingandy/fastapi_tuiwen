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
    # 基础配置
    TABLE_PREFIX: str = Field("tw_", description="table prefix")
    DEBUG: bool = Field(False, description="debug mode", json_schema_extra={"env_default": "False"})
    ACCOUNT_ID_PREFIX: str = Field("twid_", description="account id prefix")

    # JWT 密钥（支持环境变量 或 文件）
    SECRET_KEY: Optional[str] = Field(None, description="token密钥，优先级高于文件")
    SECRET_KEY_FILE: Optional[str] = Field(None, description="从文件读取token密钥")

    # 静态资源
    STATIC_URL: str = Field("static/", description="static url")
    ALLOWED_IMAGE_FORMATS: str = Field("jpg,jpeg,png", description="allowed image formats")

    # PostgreSQL
    POSTGRES_HOST: str = Field("postgresql", description="postgres server")
    POSTGRES_PORT: int = Field(5432, description="postgres port")
    POSTGRES_USER: str = Field("postgres", description="postgres user")
    POSTGRES_PASSWORD: Optional[str] = Field(None, description="postgres password")
    POSTGRES_PASSWORD_FILE: Optional[str] = Field(None, description="path to password file")
    POSTGRES_DB: str = Field("app_db", description="postgres database")

    # 时区 & Token 过期
    TIME_ZONE: str = Field("Asia/Shanghai", description="time zone")
    REFRESH_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 28)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60 * 24 * 1)

    # ===================== Redis 配置=====================
    REDIS_HOST: str = Field("127.0.0.1", description="redis host")
    REDIS_PORT: int = Field(6379, description="redis port")
    REDIS_DB: int = Field(0, description="redis database")
    REDIS_PASSWORD: Optional[str] = Field(
        default=None,
        validate_default=True,
        description="Redis 密码，优先从文件读取"
    )
    REDIS_PASSWORD_FILE: Optional[str] = Field(
        default=None,
        description="Redis 密码文件路径"
    )
    REDIS_SOCKET_TIMEOUT: int = Field(2, description="redis socket timeout")
    REDIS_EXPIRE: int = Field(30, description="redis expire")
    # ====================================================================

    BACKEND_CORS_ORIGINS: Annotated[
        list[str] | str, BeforeValidator(parse_cors)
    ]


    # CORS
    BACKEND_CORS_ORIGINS: Annotated[list[str] | str, BeforeValidator(parse_cors)]=Field(default_factory=list)

    # ===================== 环境文件加载规则 =====================
    class Config:
        # 本地开发：.env.development
        # Docker 中：不加载任何 env 文件，完全走环境变量
        env_file = ".env.develop" if not os.getenv("DOCKER_MODE") else None
        env_file_encoding = "utf-8"
        extra = "ignore"

    # ===================== 数据库连接串（计算属性） =====================
    @computed_field
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

    # ===================== 从文件加载密码/密钥 =====================
    @model_validator(mode="after")
    def load_secrets_from_files(self):
        """
        只有配置了 FILE 路径时才读取
        避免 Docker 内没有挂载 secret 直接报错崩溃
        """
        # 1. Postgres 密码
        if self.POSTGRES_PASSWORD_FILE:
            try:
                with open(self.POSTGRES_PASSWORD_FILE, "r", encoding="utf-8") as f:
                    self.POSTGRES_PASSWORD = f.read().strip()
                logger.info("从文件加载 PostgreSQL 密码成功")
            except Exception as e:
                logger.error(f"加载 PostgreSQL 密码文件失败: {e}")
                raise RuntimeError("无法加载 PostgreSQL 密码") from e

        # 2. Redis 密码
        if self.REDIS_PASSWORD_FILE:
            try:
                with open(self.REDIS_PASSWORD_FILE, "r", encoding="utf-8") as f:
                    self.REDIS_PASSWORD = f.read().strip()
                logger.info("从文件加载 Redis 密码成功")
            except Exception as e:
                logger.error(f"加载 Redis 密码文件失败: {e}")
                raise RuntimeError("无法加载 Redis 密码") from e

        # 3. JWT 密钥
        if self.SECRET_KEY_FILE and not self.SECRET_KEY:
            try:
                with open(self.SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                    self.SECRET_KEY = f.read().strip()
                logger.info("从文件加载 SECRET_KEY 成功")
            except Exception as e:
                logger.error(f"加载 SECRET_KEY 文件失败: {e}")
                raise RuntimeError("无法加载 SECRET_KEY") from e

        # 强制必须有 SECRET_KEY
        if not self.DEBUG and not self.SECRET_KEY:
            raise ValueError("SECRET_KEY 未配置，必须通过环境变量或文件指定")

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
    notices = 'notices'


@lru_cache
def get_settings():
    return Settings()
