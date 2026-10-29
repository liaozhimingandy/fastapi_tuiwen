#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:59
    @Desc: 帖子业务服务层 —— 发布 / 列表 / 可见性 / 删除
=================================================
"""
import uuid
from dataclasses import dataclass

from src.tuiwen.dal.post import PostDAO
from src.tuiwen.model.post import Post, RightStatusEnum


@dataclass
class PostService:
    """帖子业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_post_service 里是 PostService(dao=dao))。
    """

    dao: PostDAO

    async def create(self, post: Post):
        """
        新增帖子

        Args:
            post: 已组装好的帖子实体(含服务端生成的 post_id / from_ip)

        Returns:
            Post: 落库后的帖子实体(未 commit)
        """
        instance = await self.dao.create(post)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    async def delete_by_post_id(self, post_id: uuid.UUID, account_id: uuid.UUID):
        """
        删除帖子(带归属校验)

        Args:
            post_id: 帖子ID
            account_id: 当前登录账户ID, 仅作者本人可删除

        Returns:
            bool: 是否删除到记录; False 表示帖子不存在或不属于该账户
        """
        affected = await self.dao.delete_by_id(post_id, account_id)
        await self.dao.write_db.commit()
        return affected

    async def update_post_right(self, post_id: uuid.UUID, account_id: uuid.UUID,
                                right_status: RightStatusEnum):
        """
        修改帖子可见性(公开/私密)

        Args:
            post_id: 帖子ID
            account_id: 当前登录账户ID, 仅作者本人可修改
            right_status: 目标可见性(必须是枚举成员)

        Returns:
            bool: 是否更新到记录(False 表示帖子不存在或不属于该账户)
        """
        affected = await self.dao.update_post_right(post_id, account_id, right_status)
        await self.dao.write_db.commit()
        return affected

    async def get_posts_latest(self, account_id: uuid.UUID | None):
        """
        获取最近 10 条帖子(公开帖子 + 自己的帖子)

        Args:
            account_id: 当前登录账户ID; 匿名浏览时为 None(只返回公开帖)

        Returns:
            list[Post]: 帖子列表
        """
        return await self.dao.get_posts_latest(account_id)

    async def get_posts(self, account_id: uuid.UUID | None, cursor: uuid.UUID | None, limit: int):
        """
        游标分页获取帖子流

        Args:
            account_id: 当前登录账户ID; 匿名浏览时为 None(只返回公开帖)
            cursor: 游标(上一页最旧一条的 post_id)
            limit: 每页数量

        Returns:
            list[Post]: 帖子列表
        """
        return await self.dao.get_posts(account_id, cursor, limit)

    async def get_account_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None, limit: int = 10,
                                viewer_account_id: uuid.UUID | None = None):
        """
        游标分页获取某账号的帖子

        Args:
            account_id: 目标账户ID(要看谁的主页)
            cursor: 游标(上一页最旧一条的 post_id)
            limit: 每页数量
            viewer_account_id: 当前登录账户ID; 与 account_id 相同才返回全部(含私密), 否则只返回公开帖子

        Returns:
            list[Post]: 帖子列表
        """
        # 全部用关键字传参: 原先按位置传参会与 DAO 的 (account_id, cursor, ...) 顺序相反
        return await self.dao.get_account_posts(account_id=account_id, cursor=cursor, limit=limit,
                                                viewer_account_id=viewer_account_id)

    async def get_post(self, post_id: uuid.UUID, viewer_account_id: uuid.UUID | None = None):
        """
        按 post_id 查询帖子(登录态下)

        可见范围: 公开帖子 OR 自己发布的帖子; 别人的私密帖与不存在的帖子一样返回 None,
        避免用 404/403 的差异去探测「某个 post_id 是否存在」。

        Args:
            post_id: 帖子ID
            viewer_account_id: 当前登录账户ID

        Returns:
            Post | None: 可见时返回实体, 否则 None
        """
        # NOTE: 字段名必须是 "id" —— 主键列已从 post_id 改名为 id(对外 JSON 仍是 post_id),
        #       传旧名会被 _validate_field_names 拦成 ValueError(500)
        return await self.dao.get_visible_post(post_id, viewer_account_id)

    async def get_s_post(self, post_id: uuid.UUID):
        """
        查询公开帖子(匿名可见)

        Args:
            post_id: 帖子ID

        Returns:
            Post | None: 仅当帖子为公开状态时返回实体

        """
        return await self.dao.get_s_post(post_id)
