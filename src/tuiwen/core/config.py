import secrets
from typing import Any, Annotated

from pydantic import computed_field, BeforeValidator, AnyUrl
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    TABLE_PREFIX: str
    DEBUG: bool
    ACCOUNT_ID_PREFIX: str
    # SECRET_KEY: str = secrets.token_urlsafe(16)
    SECRET_KEY: str = 'tw-insecure-5xlvJWvZ_TOiJzKvtpTuBMfllIJ1WE7gvODgA41dvnA'
    STATIC_URL: str
    ALLOWED_IMAGE_FORMATS: str
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    TIME_ZONE: str = "Asia/Shanghai"
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 28
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 1

    BACKEND_CORS_ORIGINS: Annotated[
        list[str] | str, BeforeValidator(parse_cors)
    ]

    model_config = SettingsConfigDict(env_ignored_types=True, extra='ignore')

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


settings = Settings()
