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
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from src.tuiwen.common.exceptions import BizError
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
            like: 已组装好的点赞实体(target_id / target_type / account_id)

        Returns:
            Like: 落库后的点赞实体(未 commit, 事务由上层 API 控制)

        Raises:
            BizError: 409 —— 已经点过赞(靠联合唯一索引兜底)

        说明: 不做重复点赞的前置判断, 直接把唯一索引冲突转成 409 ——
              原实现没有捕获, 重复点赞最终表现为 500。
        """
        try:
            instance = await self.dao.create(like)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)
            return instance
        except IntegrityError:
            await self.dao.write_db.rollback()
            raise BizError(code=409, message="已经点过赞了")

    async def like_count(self, target_id: uuid.UUID):
        """
        统计某帖子的点赞总数

        Args:
            target_id: 目标对象ID

        Returns:
            int: 点赞总数
        """
        # 仅统计帖子类型(target_type=POST)的点赞
        return await self.dao.count(target_type=Like.TargetTypeEnum.POST, target_id=target_id)

    async def delete_like(self, target_id: uuid.UUID, account_id: uuid.UUID,
                          target_type: int = Like.TargetTypeEnum.POST):
        """
        取消当前用户对某对象的点赞

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型, 显式传入以免将来支持评论点赞时误删同 ID 的记录

        Returns:
            bool: True 表示确实取消到了记录; False 表示本来就没点过赞

        NOTE: 原实现丢弃了 DAO 的 rowcount 恒返回 True, 现在透传真实结果。
        """
        affected = await self.dao.delete_like(target_id=target_id, account_id=account_id,
                                              target_type=target_type)
        await self.dao.write_db.commit()
        return bool(affected)

    async def get_like_count(self, target_id: uuid.UUID, account_id: uuid.UUID):
        """
        查询点赞总数与当前用户是否已点赞

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        return await self.dao.get_like_count(target_id=target_id, account_id=account_id)
