#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 20:53
    @Desc: 点赞业务服务层 —— 统计 / 取消 / 查询点赞状态
=================================================
"""
from dataclasses import dataclass

from src.tuiwen.dal.like import LikeDAO
from src.tuiwen.model.like import Like


@dataclass
class LikeService:
    """点赞业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: LikeDAO

    async def create(self, like: Like):
        """
        新增一条点赞记录

        Args:
            like: 已组装好的点赞实体(obj_id / obj_type / account_id)

        Returns:
            Like: 落库后的点赞实体(未 commit, 事务由上层 API 控制)
        """
        return await self.dao.create(like)

    async def like_count(self, obj_id: str):
        """
        统计某帖子的点赞总数

        Args:
            obj_id: 目标对象ID

        Returns:
            int: 点赞总数
        """
        # 仅统计帖子类型(obj_type=POST)的点赞
        return await self.dao.count(obj_type=Like.ObjTypeEnum.POST, obj_id=obj_id)

    async def delete_like(self, obj_id: str, account_id: str):
        """
        取消当前用户对某对象的点赞

        Args:
            obj_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            bool: True 表示确实取消到了记录; False 表示本来就没点过赞
        """
        return await self.dao.delete_like(obj_id=obj_id, account_id=account_id)

    async def get_like_count(self, obj_id: str, account_id: str):
        """
        查询点赞总数与当前用户是否已点赞

        Args:
            obj_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        return await self.dao.get_like_count(obj_id=obj_id, account_id=account_id)
