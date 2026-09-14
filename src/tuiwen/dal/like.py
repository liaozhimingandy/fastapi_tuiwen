#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 20:51
    @Desc: 
=================================================
"""
from sqlmodel import delete, select, exists

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.post.models import Like


class LikeDAO(BaseDAO[Like]):
    model = Like

    async def delete_like(self, obj_id: str, account_id: str):
        statement = delete(Like).where(Like.obj_id == obj_id, Like.account_id == account_id,
                                       Like.obj_type == Like.ObjTypeEnum.POST)
        with self.write_db() as session:
            await session.exec(statement)
            await session.commit()

    async def get_like_count(self, obj_id: str, account_id: str):
        statement = select(Like.id).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST)
        statement_sub = select(Like).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST,
                                           Like.account_id == account_id)
        statement2 = select(exists().select_from(statement_sub))
        with self.read_db() as session:
            like_count = len((await session.exec(statement)).all())
            is_liked = (await session.exec(statement2)).first()

            return {'like_count': like_count, 'is_liked': is_liked}