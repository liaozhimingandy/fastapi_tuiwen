#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:55
    @Desc: 帖子数据访问层 —— 列表(含可见性过滤)、游标分页、可见性更新、删除
=================================================
"""
import uuid

from sqlmodel import delete, update, select, or_

from src.tuiwen.dal.base import BaseDAO
from model.post import Post, RightStatusEnum


class PostDAO(BaseDAO[Post]):
    model = Post

    # ---------------------------------------------------------
    # 写操作
    # ---------------------------------------------------------
    async def delete_by_post_id(self, post_id: uuid.UUID, account_id: str) -> bool:
        """
        按 post_id + account_id 删除帖子(硬删除), 保证只有作者本人能删

        Args:
            post_id: 帖子ID
            account_id: 作者账户ID

        Returns:
            bool: True 表示删除到记录; False 表示帖子不存在或不属于该作者

        事务: 只执行不提交, 由上层统一 commit
        """
        statement = delete(Post).where(Post.post_id == post_id, Post.account_id == account_id)
        result = await self.exec_write(statement, "delete_by_post_id")
        return bool(result.rowcount)

    async def update_post_right(self, post_id: uuid.UUID, account_id: str, right_status: int) -> bool:
        """
        更新帖子可见性状态(公开/私密)

        Args:
            post_id: 帖子ID
            account_id: 作者账户ID(归属校验)
            right_status: 目标可见性枚举值

        Returns:
            bool: True 表示更新到记录; False 表示帖子不存在或不属于该作者

        事务: 只执行不提交, 由上层统一 commit
        """
        statement = (update(Post).where(Post.post_id == post_id, Post.account_id == account_id)
                     .values(right_status=right_status))
        result = await self.exec_write(statement, "update_post_right")
        return bool(result.rowcount)

    # ---------------------------------------------------------
    # 读操作(均走 exec_read, 默认读库 + 统一埋点)
    # ---------------------------------------------------------
    async def get_posts_latest(self, account_id: str, limit: int = 10) -> list[Post]:
        """
        获取最近的帖子(按创建时间倒序)

        可见范围: 公开帖子 OR 自己发布的帖子

        Args:
            account_id: 当前登录账户ID
            limit: 返回条数, 默认 10

        Returns:
            list[Post]: 帖子列表
        """
        limit, _ = self._safe_page(limit, 0)
        statement = (select(Post)
                     .where(or_(Post.right_status == RightStatusEnum.PUBLIC, Post.account_id == account_id))
                     # 排序统一用 .desc() 显式表达:
                     #   - 传字符串 "-create_at" 会在编译期抛 CompileError;
                     #   - 写 -Post.create_at 也不是 DESC, SQLAlchemy 会编译成算术取负
                     #     `ORDER BY -create_at`, 对时间/字符串列属于错误语义且用不上索引
                     .order_by(Post.create_at.desc())
                     .limit(limit))
        return list((await self.exec_read(statement, "get_posts_latest")).all())

    async def get_posts(self, account_id: str, cursor: uuid.UUID | None, limit: int = 10) -> list[Post]:
        """
        帖子流游标分页

        可见范围: 公开帖子 OR 自己发布的帖子;
        翻页方式: post_id < cursor(uuid7 时间有序, 因此可直接比较大小)

        Args:
            account_id: 当前登录账户ID
            cursor: 游标, 上一页最旧一条的 post_id; 为空表示第一页
            limit: 每页数量, 默认 10

        Returns:
            list[Post]: 帖子列表
        """
        limit, _ = self._safe_page(limit, 0)
        statement = select(Post).where(
            or_(Post.right_status == RightStatusEnum.PUBLIC, Post.account_id == account_id))

        # 仅当有游标时追加翻页条件
        if cursor:
            statement = statement.where(Post.post_id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_posts")).all())

    async def get_account_posts(self, account_id: str, cursor: uuid.UUID | None = None, limit: int = 10,
                                viewer_account_id: str | None = None) -> list[Post]:
        """
        查询指定账号的帖子(uuid7 游标分页)

        可见范围: 查看者本人 → 该账号全部帖子; 否则 → 仅公开帖子。
        之前用 `if not account_id == account_id` 判断, 条件恒为 False, 可见性过滤是死分支;
        这里显式引入 viewer_account_id(当前登录用户) 让该分支真正生效。

        Args:
            account_id: 目标账户ID(要看谁的主页)
            cursor: 游标, 上一页最旧一条的 post_id; 为空表示第一页
            limit: 每页数量, 默认 10
            viewer_account_id: 发起请求的当前登录账户ID; 传入 None 时按「只看公开」处理

        Returns:
            list[Post]: 帖子列表
        """
        limit, _ = self._safe_page(limit, 0)
        statement = select(Post).where(Post.account_id == account_id)

        # 如果查看者就是号主本人, 返回全部; 否则只返回公开帖子
        if viewer_account_id != account_id:
            statement = statement.where(Post.right_status == RightStatusEnum.PUBLIC)

        # 仅当有游标时添加时间条件
        if cursor:
            statement = statement.where(Post.post_id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_account_posts")).all())

    async def get_s_post(self, post_id: uuid.UUID) -> Post | None:
        """
        查询单条公开帖子(匿名可见)

        Args:
            post_id: 帖子ID

        Returns:
            Post | None: 仅当帖子为 PUBLIC 时返回实体
        """
        statement = select(Post).where(Post.post_id == post_id, Post.right_status == RightStatusEnum.PUBLIC)
        return (await self.exec_read(statement, "get_s_post")).first()
