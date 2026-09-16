#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 20:51
    @Desc: 点赞数据访问层 —— 取消点赞 / 点赞统计
=================================================
"""
from sqlmodel import delete, select, exists

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.like import Like


class LikeDAO(BaseDAO[Like]):
    # 绑定 DAO 对应的 ORM 模型
    model = Like

    async def delete_like(self, obj_id: str, account_id: str) -> bool:
        """
        取消当前用户对某帖子的点赞(硬删除)

        Args:
            obj_id: 目标对象ID
            account_id: 点赞人账户ID

        Returns:
            bool: True 表示确实删除到记录; False 表示本来就没点赞

        事务: 只执行不提交, 由上层决定 commit 时机(遵循「DAO 不提交事务」的规范)
        """
        statement = delete(Like).where(Like.obj_id == obj_id, Like.account_id == account_id,
                                       Like.obj_type == Like.ObjTypeEnum.POST)
        # exec_write 内部已统一走主库 + 埋点, 返回 CursorResult, rowcount 即影响行数
        result = await self.exec_write(statement, "delete_like")
        return bool(result.rowcount)

    async def get_like_count(self, obj_id: str, account_id: str) -> dict:
        """
        统计某帖子的点赞总数, 并判断当前用户是否已点赞

        Args:
            obj_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        # 子查询: 当前用户对该帖子的点赞记录
        statement_sub = select(Like.id).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST,
                                              Like.account_id == account_id)
        # 是否存在的布尔查询: SELECT EXISTS (SELECT id FROM ...)
        statement_exists = select(exists(statement_sub))

        # 点赞总数直接用 COUNT(*), 避免把全部主键捞回进程内再 len() 统计
        like_count = await self.count(obj_id=obj_id, obj_type=Like.ObjTypeEnum.POST)
        # EXISTS 返回标量, 统一转成 bool(数据库驱动可能返回 0/1)
        is_liked = await self._execute_scalar(self._get_read_session(), statement_exists, "is_liked")

        return {'like_count': like_count, 'is_liked': bool(is_liked)}
