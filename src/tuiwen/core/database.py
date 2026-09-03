#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""=================================================
    @Project: FastAPIDemo
    @File： database.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/1/11 11:44
    @Desc: 
================================================="""
from typing import Annotated, TypeVar

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.tuiwen.core.config import get_settings
from ..utils.logger import logger

# 创建异步引擎
# sqlite_file_name = "tuiwen.sqlite3"
# DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_file_name}"
# DATABASE_URL = postgresql+asyncpg://zhiming:zhiming@localhost:5432/tuiwen

settings = get_settings()
DATABASE_URL = str(settings.SQLALCHEMY_DATABASE_URI)
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=not settings.DEBUG,
    pool_pre_ping=True,          # 自动检测失效连接，自动重连（生产必备）
    pool_recycle=3600,           # 连接1小时后强制回收，避免超时失效
    pool_size=5,                 # 常驻连接数
    max_overflow=10,             # 峰值最大额外连接数
    connect_args={"timeout": 60} # 连接超时时间
    )  # Annotated[bool, Doc("是否显示数据库层面日志")]

# 创建异步session
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# 泛型，用于 add_instance 精准类型提示
T = TypeVar("T")

def _import_all_models() -> None:
    """集中导入所有模型，确保元数据注册到 metadata
    单独抽成函数，避免循环导入，同时保证建表前所有模型已加载
    """
    from src.tuiwen.account.models import Account
    from src.tuiwen.post.models import Post, Comment, Like, Image, Follow
    from src.tuiwen.log.models import Log

async def init_db():
    """初始化数据库：仅创建不存在的表（不删数据，启动时调用）"""
    _import_all_models()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("初始化数据库成功")

async def drop_and_create_tables() -> None:
    """【危险操作】删除所有表后重建，仅用于开发环境重置数据"""
    _import_all_models()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.warning("已删除并重建所有数据库表,数据已清空")

async def add_instance(session: Annotated[AsyncSession, "会话对象"], instance: Annotated[T, "任意对象"]) -> T:
    """
    添加实例到数据库并提交、刷新
    只做数据库操作，不耦合 HTTP 层逻辑，异常由上层业务处理
    """
    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
        return instance
    except IntegrityError as e:
        await session.rollback() # 回滚事务
        logger.error(f"数据库唯一约束冲突: {str(e)}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请勿重复提交")
    except SQLAlchemyError as e:
        await session.rollback()
        logger.error(f"数据库操作失败: {str(e)}", exc_info=True)
        raise

# ========== 4. asyncpg 原生连接池（单例） ==========
_asyncpg_pool: asyncpg.Pool | None = None

async def get_async_pool()->asyncpg.Pool:
    """获取 asyncpg 原生连接池（单例，用于批量操作等特殊场景）"""
    global _asyncpg_pool
    if _asyncpg_pool is None:
        _asyncpg_pool = asyncpg.create_pool(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            min_size=1,
            max_size=10,
            max_queries=50000,
            max_inactive_connection_lifetime=300.0,
            timeout=60.0,
        )
        logger.info("asyncpg 原生连接池初始化完成")
    return _asyncpg_pool


async def close_async_pool() -> None:
    """关闭 asyncpg 连接池，应用停机时调用"""
    global _asyncpg_pool
    if _asyncpg_pool is not None:
        await _asyncpg_pool.close()
        _asyncpg_pool = None
        logger.info("❌ asyncpg pool closed")

async def dispose_engine() -> None:
    """销毁 SQLAlchemy 引擎，释放所有连接，应用停机时调用"""
    await engine.dispose()
    logger.info("❌ 数据库引擎已销毁,所有连接已释放")

async def init_postgres():
    """
    Postgres 完整初始化函数，启动阶段执行
    1. 验证 SQLAlchemy 引擎连通性
    2. 初始化 asyncpg 原生连接池
    3. 自动创建数据表
    """
    # 1. 测试 SQLAlchemy 引擎能否正常连接数据库
    async with AsyncSessionLocal() as session:
        # 执行一条简单SQL探测连通性
        await session.execute(text("SELECT 1"))
    logger.info("✅ SQLAlchemy 数据库引擎连通测试成功")

    # 2. 初始化 asyncpg 原生连接池
    await get_async_pool()

    # 3. 创建不存在的数据表（不会覆盖已有数据）
    # await init_db()

    logger.info("✅ PostgreSQL 完整初始化完成")

if __name__ == "__main__":
    import asyncio

    asyncio.run(drop_and_create_tables())