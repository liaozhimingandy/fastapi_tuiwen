#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:59
    @Desc: 
=================================================
"""
import uuid

from src.tuiwen.dal.post import PostDAO
from src.tuiwen.post.models import Post


class PostService:
    dao: PostDAO

    async def create(self, post: Post):
        return await self.dao.create(post)

    async def delete_by_post_id(self, post_id: uuid.UUID, account_id: str):
        return await self.dao.delete_by_post_id(post_id, account_id)

    async def update_post_right(self, post_id: uuid.UUID, account_id: str, right_status: int):
        return await self.dao.update_post_right(post_id, account_id, right_status)

    async def get_posts_latest(self, account_id: str):
        return await self.dao.get_posts_latest(account_id)

    async def get_posts(self, account_id: str, cursor: uuid.UUID, limit: int):
        return await self.dao.get_posts(account_id, cursor, limit)

    async def get_account_posts(self, post_id: uuid.UUID, account_id: str, limit: int = 10):
        return await self.dao.get_account_posts(post_id, account_id, limit)

    async def get_post(self, post_id: uuid.UUID):
        pass

    async def get_s_post(self, post_id: uuid.UUID):
        pass