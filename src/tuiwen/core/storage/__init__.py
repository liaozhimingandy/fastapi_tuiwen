import os
from .base import Storage
from .local import LocalStorage
from ... import get_settings


def get_storage() -> Storage:
    """根据环境变量返回存储实例，业务层只依赖 Storage 基类"""
    stype = os.getenv("STORAGE_TYPE", "local")
    return LocalStorage(
        base_dir=get_settings().VIDEO_STORAGE_DIR,
        static_prefix=get_settings().VIDEO_STORAGE_URL_PREFIX,
    )

storage = get_storage()
