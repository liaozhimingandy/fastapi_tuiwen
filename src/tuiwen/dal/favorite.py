#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： favorite.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/29
    @Desc: 收藏数据访问层 —— 取消收藏 / 收藏统计 / 收藏列表反查
=================================================
"""
import uuid
from typing import Sequence

from sqlalchemy import func
from sqlmodel import delete, select, exists

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.favorite import Favorite
from src.tuiwen.model.post import Post, RightStatusEnum


class FavoriteDAO(BaseDAO[Favorite]):
    # 绑定 DAO 对应的 ORM 模型
    model = Favorite

    async def delete_favorite(self, target_id: uuid.UUID, account_id: uuid.UUID,
                              target_type: Favorite.TargetTypeEnum = Favorite.TargetTypeEnum.POST) -> bool:
        """
        取消当前用户对某帖子的收藏(硬删除)

        Args:
            target_id: 目标对象ID
            account_id: 收藏人账户ID
            target_type: 目标对象类型

        Returns:
            bool: True 表示确实删除到记录; False 表示本来就没收藏

        事务: 只执行不提交, 由上层决定 commit 时机(遵循「DAO 不提交事务」的规范)
        """
        statement = delete(Favorite).where(Favorite.target_id == target_id, Favorite.account_id == account_id,
                                           Favorite.target_type == target_type)
        result = await self.exec_write(statement, "delete_favorite")
        return bool(result.rowcount)

    async def get_favorite_count(self, target_id: uuid.UUID, account_id: uuid.UUID,
                                 target_type: Favorite.TargetTypeEnum = Favorite.TargetTypeEnum.POST) -> dict:
        """
        统计某个目标的收藏总数, 并判断当前用户是否已收藏

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型(当前仅帖子)

        Returns:
            dict: {"favorite_count": int, "is_favorited": bool}
        """
        # 子查询: 当前用户对该目标的收藏记录
        statement_sub = select(Favorite.id).where(Favorite.target_id == target_id,
                                                  Favorite.target_type == target_type,
                                                  Favorite.account_id == account_id)
        statement_exists = select(exists(statement_sub))

        favorite_count = await self.count(target_id=target_id, target_type=target_type)
        is_favorited = await self._execute_scalar(self._get_read_session(), statement_exists, "is_favorited")

        return {'favorite_count': favorite_count, 'is_favorited': bool(is_favorited)}

    async def get_favorited_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None,
                                  limit: int = 10, viewer_account_id: uuid.UUID | None = None) -> list[Post]:
        """
        查询某账号「收藏过」的帖子(uuid7 游标分页)

        通过 tw_favorite 反查 target_id 再 JOIN 帖子表得到帖子列表。
        可见范围与「我的帖子/点赞」一致: 号主本人 → 全部(含私密收藏); 其他查看者 → 仅公开帖。
        (规范: 收藏不应默认公开, 这里按「只对自己完全可见」从严处理 ——
         非本人查看时只返回收藏中恰为公开帖的部分。)

        Args:
            account_id: 目标账户ID(要看谁收藏过的内容)
            cursor: 游标, 上一页最旧一条的 post_id; 为空表示第一页
            limit: 每页数量, 默认 10
            viewer_account_id: 当前登录账户ID; 与 account_id 相同才返回私密帖

        Returns:
            list[Post]: 帖子列表(按帖子主键倒序)
        """
        limit, _ = self._safe_page(limit, 0)
        statement = (
            select(Post)
            .join(Favorite, Favorite.target_id == Post.id)
            .where(Favorite.account_id == account_id, Favorite.target_type == Favorite.TargetTypeEnum.POST)
        )
        # 非本人查看时只返回公开帖(收藏夹默认不对外暴露私密内容)
        if viewer_account_id != account_id:
            statement = statement.where(Post.right_status == RightStatusEnum.PUBLIC)
        # 仅当有游标时追加时间条件(uuid7 主键时间有序, 直接比较大小即可翻页)
        if cursor:
            statement = statement.where(Post.id < cursor)
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_favorited_posts")).all())

    async def count_by_targets(self, target_type: Favorite.TargetTypeEnum,
                               target_ids: Sequence[uuid.UUID]) -> dict:
        """批量统计多个目标的收藏数(视频 feed 一次装配一页数据时用)

        Returns:
            dict: {target_id: favorite_count}, 没有收藏的目标不在返回里
        """
        if not target_ids:
            return {}
        statement = (
            select(Favorite.target_id, func.count())
            .where(Favorite.target_type == target_type, Favorite.target_id.in_(target_ids))
            .group_by(Favorite.target_id)
        )
        result = await self.exec_read(statement, "count_favorites_by_targets")
        return {row[0]: int(row[1]) for row in result.all()}

    async def favorited_target_ids(self, account_id: uuid.UUID | None, target_type: Favorite.TargetTypeEnum,
                                   target_ids: Sequence[uuid.UUID]) -> set:
        """批量查询某用户对哪些目标收藏过(未登录返回空集)

        Returns:
            set: 已收藏的 target_id 集合
        """
        if account_id is None or not target_ids:
            return set()
        statement = select(Favorite.target_id).where(
            Favorite.account_id == account_id,
            Favorite.target_type == target_type,
            Favorite.target_id.in_(target_ids),
        )
        result = await self.exec_read(statement, "favorited_target_ids")
        # sqlmodel session.exec 对单列 select 直接返回标量(UUID), 不是 Row 元组,
        # row[0] 会抛 'UUID' object is not subscriptable; 兼容两种返回形态
        return {row if not isinstance(row, tuple) else row[0] for row in result.all()}
