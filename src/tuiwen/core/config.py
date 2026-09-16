"""全局配置模块。

基于 pydantic-settings 的 Settings 单例，集中管理：
- JWT / Turnstile / PostgreSQL / Redis 等密钥（支持环境变量或密钥文件两种来源）
- 数据库连接串、静态资源、CORS、时区、Token 有效期等运行参数
- Docker 部署时完全走环境变量，本地开发读取 .env.develop

对外入口: get_settings()（lru_cache 单例）；OpenAPI 分组枚举 Tag 也定义在此。
"""
import os
from enum import Enum
from functools import lru_cache
from typing import Any, Annotated, Optional

from pydantic import computed_field, BeforeValidator, Field, model_validator
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings

from ..utils.logger import logger

def parse_cors(v: Any) -> list[str] | str:
    """CORS 来源的宽容解析: 允许环境变量写成逗号分隔字符串(如 "http://a.com,http://b.com")。

    Args:
        v: 原始配置值, 字符串或列表

    Returns:
        list[str] | str: 解析后的来源列表(原样返回已是列表/JSON数组的情况)

    Raises:
        ValueError: 无法识别的类型
    """
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    """应用全局配置(字段名即环境变量名, 大小写不敏感)。"""
    # 基础配置
    TABLE_PREFIX: str = Field("tw_", description="table prefix")
    DEBUG: bool = Field(False, description="debug mode", json_schema_extra={"env_default": "False"})
    ACCOUNT_ID_PREFIX: str = Field("twid_", description="account id prefix")

    # JWT 密钥（支持环境变量 或 文件）
    SECRET_KEY: Optional[str] = Field(None, description="token密钥，优先级高于文件")
    SECRET_KEY_FILE: Optional[str] = Field(None, description="从文件读取token密钥")

    # cloudflare
    TURNSTILE_SECRET_KEY: Optional[str] = Field(None, description="TURNSTILE密钥，优先级高于文件")
    TURNSTILE_SECRET_KEY_FILE: Optional[str] = Field(None, description="从文件读取密钥")

    # 静态资源
    STATIC_URL: str = Field("static/", description="static url")
    ALLOWED_IMAGE_FORMATS: str = Field("jpg,jpeg,png", description="allowed image formats")
    # 静态文件磁盘根路径（容器内物理路径）
    STORAGE_LOCAL_ROOT: str = "/app/static/medias"
    # 对外URL前缀，对应mount的路由
    STORAGE_URL_PREFIX: str = "/static/medias"

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
    REDIS_EXPIRE: int = Field(30*60, description="redis expire")

    @computed_field
    @property
    def REDIS_KEY_PREFIX(self) -> str:
        """Redis 键统一前缀, 按环境区分(dev/prod), 避免多环境共用同一 Redis 时键冲突。"""
        return f"tw:{'dev' if self.DEBUG else 'prod'}"

    # ====================================================================

    BACKEND_CORS_ORIGINS: Annotated[
        list[str] | str, BeforeValidator(parse_cors)
    ]


    # CORS
    # NOTE: 该字段上面第 100~102 行已声明过一次(无默认值), 此处重复定义;
    #       pydantic v2 不会报错, 后者覆盖前者, 属应清理的冗余
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

        # 4.TURNSTILE
        if self.TURNSTILE_SECRET_KEY_FILE and not self.TURNSTILE_SECRET_KEY:
            try:
                with open(self.TURNSTILE_SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                    self.TURNSTILE_SECRET_KEY = f.read().strip()
                logger.info("从文件加载 TURNSTILE_SECRET_KEY 成功")
            except Exception as e:
                logger.error(f"加载 TURNSTILE_SECRET_KEY 文件失败: {e}")
                raise RuntimeError("无法加载 TURNSTILE_SECRET_KEY") from e

        # 强制必须有 SECRET_KEY
        if not self.DEBUG and not self.SECRET_KEY:
            raise ValueError("SECRET_KEY 未配置，必须通过环境变量或文件指定")
        return self

class Tag(Enum):
    """OpenAPI 文档分组标签, 与 main.py 的 tags_metadata、各路由的 tags 参数一一对应。"""
    account = 'account'
    post = 'post'
    like = 'like'
    comment = 'comment'
    log = 'log'
    oauth = 'oauth'
    app = 'app'
    upload = 'upload'
    more = 'more'


# ===================== 令牌权限范围(scopes) 公共常量 =====================
# 原先定义在 account/router.py, Service 引用它会形成「Service → 路由」的反向依赖;
# 现下沉到 core, 供令牌签发(service/account.py)与依赖校验(dependencies.oauth2_scheme)共用
SCOPES_BASIC = "basic"    # 普通用户: 登录后默认授予
SCOPES_ADMIN = "admin"    # 管理权限: 需显式校验


@lru_cache
def get_settings():
    """返回全局唯一的 Settings 实例(lru_cache 缓存, 进程内只构造一次)。"""
    return Settings()
