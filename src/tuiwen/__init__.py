"""包入口: 聚合导出配置/路由/日志/生命周期函数, 供 main.py 一站式导入。

导出内容分四组:
- 工具: custom_generate_unique_id / get_version_from_txt / logger
- 配置与路由: get_settings / api_router
- 生命周期: init_postgres / init_db / init_redis / close_redis / close_async_pool / dispose_engine
- 邮件: init_mail_sender
"""
from .utils import (get_version_from_txt, custom_generate_unique_id, logger, init_mail_sender,
                    init_redis, close_redis)
from .core import get_settings
from .router import api_router
from .core import dispose_engine, close_async_pool, init_db, init_postgres

__all__ = ["custom_generate_unique_id", "get_version_from_txt", "api_router", "logger", 'get_settings',
           'dispose_engine', 'close_async_pool', "init_db", 'init_mail_sender', 'init_redis',
           'close_redis', "init_postgres"]

