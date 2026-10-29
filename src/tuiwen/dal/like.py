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
from typing import Sequence

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.like import Like
from src.tuiwen.model.post import Post, RightStatusEnum


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

    async def get_liked_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None,
                              limit: int = 10, viewer_account_id: uuid.UUID | None = None) -> list[Post]:
        """
        查询某账号「点赞过」的帖子(uuid7 游标分页)

        通过 tw_like 反查 target_id 再 JOIN 帖子表得到帖子列表。
        可见范围与「我的帖子」一致: 号主本人 → 全部(含私密); 其他查看者 → 仅公开帖。

        Args:
            account_id: 目标账户ID(要看谁点赞过的内容)
            cursor: 游标, 上一页最旧一条的 post_id; 为空表示第一页
            limit: 每页数量, 默认 10
            viewer_account_id: 当前登录账户ID; 与 account_id 相同才返回私密帖

        Returns:
            list[Post]: 帖子列表(按帖子主键倒序)
        """
        limit, _ = self._safe_page(limit, 0)
        statement = (
            select(Post)
            .join(Like, Like.target_id == Post.id)
            .where(Like.account_id == account_id, Like.target_type == Like.TargetTypeEnum.POST)
        )
        # 非本人查看时只返回公开帖(私密点赞过的内容不对外暴露)
        if viewer_account_id != account_id:
            statement = statement.where(Post.right_status == RightStatusEnum.PUBLIC)
        # 仅当有游标时追加时间条件(uuid7 主键时间有序, 直接比较大小即可翻页)
        if cursor:
            statement = statement.where(Post.id < cursor)
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_liked_posts")).all())

    async def count_by_targets(self, target_type: Like.TargetTypeEnum,
                               target_ids: Sequence[uuid.UUID]) -> dict:
        """批量统计多个目标的点赞数(视频 feed 一次装配一页数据时用)

        Args:
            target_type: 目标类型(1帖子/2视频)
            target_ids: 目标ID集合

        Returns:
            dict: {target_id: like_count}, 没有点赞的目标不在返回里
        """
        if not target_ids:
            return {}
        statement = (
            select(Like.target_id, func.count())
            .where(Like.target_type == target_type, Like.target_id.in_(target_ids))
            .group_by(Like.target_id)
        )
        result = await self.exec_read(statement, "count_likes_by_targets")
        return {row[0]: int(row[1]) for row in result.all()}

    async def liked_target_ids(self, account_id: uuid.UUID | None, target_type: Like.TargetTypeEnum,
                               target_ids: Sequence[uuid.UUID]) -> set:
        """批量查询某用户对哪些目标点过赞(未登录返回空集)

        Args:
            account_id: 用户账户ID; None 表示未登录
            target_type: 目标类型
            target_ids: 目标ID集合

        Returns:
            set: 已点赞的 target_id 集合
        """
        if account_id is None or not target_ids:
            return set()
        statement = select(Like.target_id).where(
            Like.account_id == account_id,
            Like.target_type == target_type,
            Like.target_id.in_(target_ids),
        )
        result = await self.exec_read(statement, "liked_target_ids")
        return {row[0] for row in result.all()}
