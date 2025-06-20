import os
from functools import lru_cache
from typing import Any, Annotated

from pydantic import computed_field, BeforeValidator, Field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    TABLE_PREFIX: str = Field("tw_", description="table prefix")
    DEBUG: bool = Field(False, description="debug mode")
    ACCOUNT_ID_PREFIX: str = Field("twid_", description="account id prefix")
    # SECRET_KEY: str = secrets.token_urlsafe(16)
    SECRET_KEY: str = 'tw-insecure-5xlvJWvZ_TOiJzKvtpTuBMfllIJ1WE7gvODgA41dvnA'
    STATIC_URL: str = Field("static/", description="static url")
    ALLOWED_IMAGE_FORMATS: str = Field("jpg,jpeg,png", description="allowed image formats")
    POSTGRES_SERVER: str = Field("postgresql", description="postgres server")
    POSTGRES_PORT: int = Field(5432, description="postgres port")
    POSTGRES_USER: str = Field("postgres", description="postgres user")
    POSTGRES_PASSWORD: str = Field(..., description="postgres password")
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
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )


@lru_cache
def get_settings():
    return Settings()
