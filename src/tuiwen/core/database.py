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
from typing import Any, Annotated

import asyncpg

from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status, Depends
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.tuiwen.core import config
from src.tuiwen.core.config import get_settings

# 创建异步引擎
# sqlite_file_name = "tuiwen.sqlite3"
# DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_file_name}"
# DATABASE_URL = postgresql+asyncpg://zhiming:zhiming@localhost:5432/tuiwen
DATABASE_URL = str(get_settings().SQLALCHEMY_DATABASE_URI)
engine = create_async_engine(DATABASE_URL, echo=not get_settings().DEBUG)  # Annotated[bool, Doc("是否显示数据库层面日志")]

# 创建异步session
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=True)

async def create_table_async():
    """ 异步的形式创建数据库 """

    from src.tuiwen.account.models import Account
    from src.tuiwen.post.models import Post, Comment, Like, Image, Follow
    from src.tuiwen.log.models import Log
    async with engine.begin() as conn:
        # 使用 SQLAlchemy 的异步连接创建表
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
        print("Tables created successfully")  # 添加日志输出，确认创建


async def init_db():
    """
    初始化数据库,创建表
    :return:
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        print("Tables created successfully")  # 添加日志输出，确认创建


async def get_async_pool(settings: Annotated[config.Settings, Depends(get_settings)]):
    """获取数据库连接池;适合手动管理连接"""
    return await asyncpg.create_pool(
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


async def add_instance(session, instance) -> Any:
    """将实例添加到数据库"""
    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        await session.rollback() # 回滚事务
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请勿重复提交")
    except Exception as e:
        await session.rollback() # 回滚事务
        raise e  # 将异常重新抛出

    return instance

if __name__ == "__main__":
    import asyncio

    asyncio.run(create_table_async())