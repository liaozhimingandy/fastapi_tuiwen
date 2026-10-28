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
from sqlalchemy import func
from sqlmodel import delete, select, exists

import uuid

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.like import Like
from src.tuiwen.model.post import Post


class LikeDAO(BaseDAO[Like]):
    # 绑定 DAO 对应的 ORM 模型
    model = Like

    async def delete_like(self, target_id: uuid.UUID, account_id: uuid.UUID,
                          target_type: Like.TargetTypeEnum = Like.TargetTypeEnum.POST) -> bool:
        """
        取消当前用户对某帖子的点赞(硬删除)

        Args:
            target_id: 目标对象ID
            account_id: 点赞人账户ID
            target_type: 目标对象类型

        Returns:
            bool: True 表示确实删除到记录; False 表示本来就没点赞

        事务: 只执行不提交, 由上层决定 commit 时机(遵循「DAO 不提交事务」的规范)
        """
        statement = delete(Like).where(Like.target_id == target_id, Like.account_id == account_id,
                                       Like.target_type == target_type)
        # exec_write 内部已统一走主库 + 埋点, 返回 CursorResult, rowcount 即影响行数
        result = await self.exec_write(statement, "delete_like")
        return bool(result.rowcount)

    async def get_like_count(self, target_id: uuid.UUID, account_id: uuid.UUID,
                             target_type: Like.TargetTypeEnum = Like.TargetTypeEnum.POST) -> dict:
        """
        统计某个目标的点赞总数, 并判断当前用户是否已点赞

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型(帖子/评论)

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        # 子查询: 当前用户对该目标的点赞记录
        statement_sub = select(Like.id).where(Like.target_id == target_id, Like.target_type == target_type,
                                              Like.account_id == account_id)
        # 是否存在的布尔查询: SELECT EXISTS (SELECT id FROM ...)
        statement_exists = select(exists(statement_sub))

        # NOTE: 这里必须用入参 target_type, 原先写死成 POST —— 统计评论点赞数时会把
        #       该 target_id 对应帖子的点赞数算进来(只要 ID 碰巧相同就会串数据)
        like_count = await self.count(target_id=target_id, target_type=target_type)
        # EXISTS 返回标量, 统一转成 bool(数据库驱动可能返回 0/1)
        is_liked = await self._execute_scalar(self._get_read_session(), statement_exists, "is_liked")

        return {'like_count': like_count, 'is_liked': bool(is_liked)}

    async def count_likes_received(self, account_id: uuid.UUID) -> int:
        """
        统计某账户「收到的赞」总数

        个人主页的获赞数原先在 FollowService 里硬编码 0, 前端拿到的是一个恒为 0 的假值;
        这里用一条带 IN 子查询的 COUNT 把它算出来。

        Args:
            account_id: 被统计的账户ID(内容作者)

        Returns:
            int: 获赞总数; 该账户没有任何内容或没有赞时为 0

        事务: 只读, 走读库

        NOTE: 只统计帖子。Like.TargetTypeEnum 目前只有 POST 一个取值(评论点赞尚未实现),
              等枚举加上 COMMENT 后, 这里要一并加 `target_id IN (该账户的评论)` 的分支。
        """
        # 该账户发布的帖子主键集合 —— 只查 id, 不取实体
        post_ids = select(Post.id).where(Post.account_id == account_id)

        statement = (
            select(func.count())
            .select_from(Like)
            .where(Like.target_type == Like.TargetTypeEnum.POST, Like.target_id.in_(post_ids))
        )
        total = await self._execute_scalar(self._get_read_session(), statement, "count_likes_received")
        return int(total or 0)
