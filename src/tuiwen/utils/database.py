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
import asyncpg
from dotenv import load_dotenv, find_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.tuiwen.config import settings

# 创建异步引擎
# sqlite_file_name = "tuiwen.sqlite3"
# DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_file_name}"
DATABASE_URL = str(settings.SQLALCHEMY_DATABASE_URI)
engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)  # Annotated[bool, Doc("是否显示数据库层面日志")]

# 创建异步session
async_session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def create_table_async():
    """ 异步的形式创建数据库 """
    # 加载环境变量
    _ = load_dotenv(find_dotenv(filename="../.env"))
    from src.tuiwen.account.models import Account
    from src.tuiwen.post.models import Post, Comment, Like, Image
    async with engine.begin() as conn:
        # 使用 SQLAlchemy 的异步连接创建表
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
        print("Tables created successfully")  # 添加日志输出，确认创建


async def get_async_pool():
    """获取数据库连接池;适合手动管理连接"""
    return await asyncpg.create_pool(
        user=get_settings().POSTGRES_USER,
        password=get_settings().POSTGRES_PASSWORD,
        database=get_settings().POSTGRES_DB,
        host=get_settings().POSTGRES_HOST,
        port=get_settings().POSTGRES_PORT,
        min_size=1,
        max_size=10,
        max_queries=50000,
        max_inactive_connection_lifetime=300.0,
        timeout=60.0,
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(create_table_async())