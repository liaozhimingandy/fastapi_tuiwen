import os
from .base import Storage
from .local import LocalStorage


def get_storage() -> Storage:
    """根据环境变量返回存储实例，业务层只依赖 Storage 基类"""
    stype = os.getenv("STORAGE_TYPE", "local")
    return LocalStorage(
        base_dir=os.getenv("VIDEO_STORAGE_DIR", "/data/videos"),
        static_prefix=os.getenv("STATIC_PREFIX", "/static/videos"),
    )

storage = get_storage()
