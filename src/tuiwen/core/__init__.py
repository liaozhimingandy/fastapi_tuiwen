#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""core 包对外出口: 配置(get_settings/Settings/Tag/权限常量) + 数据库基础设施。"""
from .config import get_settings, Settings, Tag, SCOPES_BASIC, SCOPES_ADMIN
from .database import (AsyncSessionLocal, add_instance, get_async_pool, init_db,
                       close_async_pool, dispose_engine, init_postgres)

__all__ = [
    "database",
    "get_settings",
    "Settings",
    "Tag",
    "SCOPES_BASIC",
    "SCOPES_ADMIN",
    "AsyncSessionLocal",
    "add_instance",
    "get_async_pool",
    "init_db",
    "close_async_pool",
    "dispose_engine",
    "init_postgres"
]
