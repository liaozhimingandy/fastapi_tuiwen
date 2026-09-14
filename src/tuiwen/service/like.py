#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 20:53
    @Desc: 
=================================================
"""
from dataclasses import dataclass

from sqlalchemy import delete

from src.tuiwen.dal.like import LikeDAO
from src.tuiwen.post.models import Like


@dataclass
class LikeService:
    dao: LikeDAO

    async def like_count(self, obj_id: str):
        return await self.dao.count(obj_type=Like.ObjTypeEnum.POST, obj_id=obj_id)

    async def delete_like(self, obj_id: str, account_id: str):
        return await self.dao.delete_like(obj_id=obj_id, account_id=account_id)

    async def get_like_count(self, obj_id: str, account_id: str):
        return await self.dao.get_like_count(obj_id=obj_id, account_id=account_id)


