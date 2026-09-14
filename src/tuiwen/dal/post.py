#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:55
    @Desc: 
=================================================
"""
import uuid

from sqlmodel import delete, update, select, or_
from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.post.models import Post, RightStatusEnum


class PostDAO(BaseDAO[Post]):


    async def delete_by_post_id(self, post_id: uuid.UUID, account_id):
        statement = delete(Post).where(Post.post_id == post_id, Post.account_id == account_id)
        with self.write_db() as session:
            await session.exec(statement)
            await session.commit()

    async def update_post_right(self, post_id: uuid.UUID, account_id: str, right_status: int):
        statement = update(Post).where(Post.post_id == post_id, Post.account_id == account_id).values(
            right_status=right_status)

        with self.write_db() as session:
            await session.exec(statement)
            await session.commit()

    async def get_posts_latest(self, account_id: str, limit: int = 10):
        statement = (select(Post).where(
            or_(Post.right_status == RightStatusEnum.PUBLIC, Post.account_id == account_id))
                     .order_by('-create_at').limit(limit))
        with self.read_db() as session:
            return (await session.exec(statement)).all()

    async def get_posts(self, account_id: str, cursor: uuid.UUID, limit: int = 10):
        statement = select(Post).where(
            or_(Post.right_status == RightStatusEnum.PUBLIC, Post.account_id == account_id))

        if cursor:
            statement = statement.where(Post.post_id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(-Post.id).limit(limit)

        with self.read_db() as session:
            return (await session.exec(statement)).all()

    async def get_account_posts(self, account_id:str, post_id: uuid.UUID, limit: int = 10):
        statement = select(Post).where(Post.account_id == account_id)
        # 如果和认证用户一致,则返回所有，否则查公开帖子
        if not account_id == account_id:
            statement = statement.where(
                Post.right_status == RightStatusEnum.PUBLIC
            )

        # 仅当有游标时添加时间条件
        if post_id:
            statement = statement.where(Post.post_id < post_id)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(-Post.id).limit(limit)

        with self.read_db() as session:
            return (await session.exec(statement)).all()
