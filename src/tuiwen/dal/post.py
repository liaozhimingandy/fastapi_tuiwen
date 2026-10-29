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
from datetime import timedelta

from sqlalchemy import String, func
from sqlmodel import delete, select, or_

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.follow import Follow
from src.tuiwen.model.like import Like
from src.tuiwen.model.post import Post, RightStatusEnum
from src.tuiwen.utils.datetime_utils import utcnow


class PostDAO(BaseDAO[Post]):
    model = Post

    # ---------------------------------------------------------
    # 写操作
    # ---------------------------------------------------------
    async def delete_by_id(self, post_id: uuid.UUID, account_id: uuid.UUID) -> bool:
        """
        按主键 id + account_id 删除帖子(硬删除), 保证只有作者本人能删

        Args:
            post_id: 帖子主键ID
            account_id: 作者账户主键

        Returns:
            bool: True 表示删除到记录; False 表示帖子不存在或不属于该作者

        事务: 只执行不提交, 由上层统一 commit
        """
        statement = delete(Post).where(Post.id == post_id, Post.account_id == account_id)
        result = await self.exec_write(statement, "delete_by_id")
        return bool(result.rowcount)

    async def update_post_right(self, post_id: uuid.UUID, account_id: uuid.UUID,
                                right_status: RightStatusEnum) -> bool:
        """
        更新帖子可见性状态(公开/私密)

        Args:
            post_id: 帖子ID
            account_id: 作者账户ID(归属校验)
            right_status: 目标可见性(枚举成员, 由 IntEnumType 负责落库转换)

        Returns:
            bool: True 表示更新到记录; False 表示帖子不存在或不属于该作者

        事务: 只执行不提交, 由上层统一 commit
        """
        statement = (update(Post).where(Post.id == post_id, Post.account_id == account_id)
                     .values(right_status=right_status))
        result = await self.exec_write(statement, "update_post_right")
        return bool(result.rowcount)

    # ---------------------------------------------------------
    # 读操作(均走 exec_read, 默认读库 + 统一埋点)
    # ---------------------------------------------------------
    async def get_posts_latest(self, account_id: uuid.UUID, limit: int = 10) -> list[Post]:
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
                     #   - 传字符串 "-created_at" 会在编译期抛 CompileError;
                     #   - 写 -Post.created_at 也不是 DESC, SQLAlchemy 会编译成算术取负
                     #     `ORDER BY -created_at`, 对时间/字符串列属于错误语义且用不上索引
                     .order_by(Post.created_at.desc())
                     .limit(limit))
        return list((await self.exec_read(statement, "get_posts_latest")).all())

    async def get_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None, limit: int = 10) -> list[Post]:
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
            statement = statement.where(Post.id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_posts")).all())

    async def get_follow_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None,
                               limit: int = 10) -> list[Post]:
        """
        关注流: 当前用户关注的人的帖子(uuid7 游标分页)

        可见范围: 关注对象的公开帖子 + 自己发布的全部帖子;
        翻页方式: post_id < cursor(uuid7 时间有序, 因此可直接比较大小)

        Args:
            account_id: 当前登录账户ID
            cursor: 游标, 上一页最旧一条的 post_id; 为空表示第一页
            limit: 每页数量, 默认 10

        Returns:
            list[Post]: 帖子列表

        NOTE: 用 IN 子查询而不是 JOIN —— 自己的帖子(不在关注表里)也要进入关注流,
              JOIN 会把它们全部漏掉。子查询先取关注集合再按 author 过滤, 语义清晰。
        """
        limit, _ = self._safe_page(limit, 0)
        # 关注对象ID集合(只取 followee_id, 不取实体)
        followee_ids = select(Follow.followee_id).where(Follow.follower_id == account_id)
        statement = select(Post).where(
            or_(
                # 关注对象的公开帖子(私密帖只对作者本人可见)
                Post.account_id.in_(followee_ids) & (Post.right_status == RightStatusEnum.PUBLIC),
                # 自己的帖子(含私密, 与首页推荐流口径一致)
                Post.account_id == account_id,
            )
        )

        # 仅当有游标时追加翻页条件
        if cursor:
            statement = statement.where(Post.id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_follow_posts")).all())

    async def get_account_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None, limit: int = 10,
                                viewer_account_id: uuid.UUID | None = None) -> list[Post]:
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
            statement = statement.where(Post.id < cursor)

        # 按创建时间倒序 + 限制数量
        statement = statement.order_by(Post.id.desc()).limit(limit)
        return list((await self.exec_read(statement, "get_account_posts")).all())

    async def get_s_post(self, post_id: uuid.UUID) -> Post | None:
        """
        查询单条公开帖子(匿名可见)

        Args:
            post_id: 帖子主键ID

        Returns:
            Post | None: 仅当帖子为 PUBLIC 时返回实体
        """
        statement = select(Post).where(Post.id == post_id, Post.right_status == RightStatusEnum.PUBLIC)
        return (await self.exec_read(statement, "get_s_post")).first()

    async def get_hot_posts(self, days: int = 7, limit: int = 10) -> list[Post]:
        """
        热门帖子: 最近 days 天的公开帖按点赞数倒序

        用子查询按帖子聚合点赞数, 再 JOIN 回帖子表排序;
        没有任何点赞的帖子不参与排序(不返回) —— 发现页只展示「有人觉得好」的内容。

        Args:
            days: 统计窗口(帖子创建时间在最近 N 天内), 默认 7
            limit: 返回条数, 默认 10

        Returns:
            list[Post]: 帖子列表(点赞多在前, 同票按时间新在前)
        """
        limit, _ = self._safe_page(limit, 0)
        # 每条帖子的点赞总数(只统计 target_type=POST 的赞)
        like_stat = (
            select(Like.target_id, func.count().label("like_total"))
            .where(Like.target_type == Like.TargetTypeEnum.POST)
            .group_by(Like.target_id)
            .subquery()
        )
        since = utcnow() - timedelta(days=days)
        statement = (
            select(Post)
            .join(like_stat, like_stat.c.target_id == Post.id)
            .where(Post.right_status == RightStatusEnum.PUBLIC, Post.created_at >= since)
            .order_by(like_stat.c.like_total.desc(), Post.id.desc())
            .limit(limit)
        )
        return list((await self.exec_read(statement, "get_hot_posts")).all())

    async def search_posts(self, keyword: str, offset: int = 0, limit: int = 10) -> list[Post]:
        """
        按关键词搜索公开帖子(content JSON 文本模糊匹配)

        content 是 JSON 列, 直接 CAST 成文本后 ILIKE 全文匹配 —— MVP 够用,
        等内容量上来再考虑 pg_trgm / 全文索引, 接口形态不变。

        Args:
            keyword: 搜索关键词(前后空白会被去掉)
            offset: 偏移量, 默认 0
            limit: 每页数量, 默认 10

        Returns:
            list[Post]: 命中的公开帖子(按时间倒序)
        """
        limit, offset = self._safe_page(limit, offset)
        # 用户输入里的 % 和 _ 是 LIKE 通配符, 先转义掉避免 "%%" 之类的意外全匹配
        escaped = keyword.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = (
            select(Post)
            .where(
                Post.right_status == RightStatusEnum.PUBLIC,
                func.cast(Post.content, String).ilike(pattern, escape="\\"),
            )
            .order_by(Post.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.exec_read(statement, "search_posts")).all())

    async def get_visible_post(self, post_id: uuid.UUID, viewer_account_id: uuid.UUID | None = None) -> Post | None:
        """
        按主键查询单条帖子, 并应用可见性过滤

        之前详情接口直接按主键取, 任何登录用户猜到 post_id 就能读到别人的私密帖;
        这里把「公开 OR 本人」条件下推到 SQL, 从数据层保证不可见即查不到。

        Args:
            post_id: 帖子主键ID
            viewer_account_id: 当前登录账户ID; 为 None 时只看公开帖子

        Returns:
            Post | None: 可见时返回实体, 不存在或不可见时返回 None
        """
        statement = select(Post).where(Post.id == post_id)
        if viewer_account_id is None:
            statement = statement.where(Post.right_status == RightStatusEnum.PUBLIC)
        else:
            statement = statement.where(
                or_(Post.right_status == RightStatusEnum.PUBLIC, Post.account_id == viewer_account_id))
        return (await self.exec_read(statement, "get_visible_post")).first()
