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
from src.tuiwen.dal.notice import NoticeDAO
from src.tuiwen.dal.post import PostDAO
from src.tuiwen.model.like import Like
from src.tuiwen.model.notice import Notice, NoticeType, NoticeTargetType
from src.tuiwen.model.post import Post


@dataclass
class LikeService:
    """点赞业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。

    post_dao / notice_dao 用于点赞成功后给帖子作者写一条 LIKE 通知;
    任一为 None 时跳过(向后兼容, 单测可不注入)。
    """

    dao: LikeDAO
    post_dao: PostDAO | None = None
    notice_dao: NoticeDAO | None = None

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
        except IntegrityError:
            await self.dao.write_db.rollback()
            raise BizError(code=409, message="已经点过赞了")

        # 点赞成功后给帖子作者写一条通知(自己赞自己不通知; 通知失败不影响点赞)。
        # 当前 Like.TargetTypeEnum 只有 POST, 将来扩了视频点赞再在这里补分支。
        if self.notice_dao is not None and self.post_dao is not None \
                and like.target_type == Like.TargetTypeEnum.POST \
                and like.account_id is not None:
            try:
                post = await self.post_dao.get_by_id(like.target_id)
                if post is not None and post.account_id != like.account_id:
                    notice = Notice(
                        account_id=post.account_id,
                        trigger_account_id=like.account_id,
                        notice_type=NoticeType.LIKE,
                        target_type=NoticeTargetType.POST,
                        target_id=post.id,
                        content={"text": "赞了你的帖子"},
                    )
                    await self.notice_dao.create(notice)
                    await self.notice_dao.write_db.commit()
            except Exception:
                await self.notice_dao.write_db.rollback()

        return instance

    async def like_count(self, target_id: uuid.UUID,
                         target_type: int = Like.TargetTypeEnum.POST):
        """
        统计某对象的点赞总数

        Args:
            target_id: 目标对象ID
            target_type: 目标对象类型(1帖子/2视频)

        Returns:
            int: 点赞总数
        """
        return await self.dao.count(target_type=target_type, target_id=target_id)

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

    async def get_like_count(self, target_id: uuid.UUID, account_id: uuid.UUID,
                             target_type: int = Like.TargetTypeEnum.POST):
        """
        查询点赞总数与当前用户是否已点赞

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型(1帖子/2视频)

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        return await self.dao.get_like_count(target_id=target_id, account_id=account_id,
                                             target_type=target_type)

    async def get_liked_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None,
                              limit: int = 10, viewer_account_id: uuid.UUID | None = None) -> list[Post]:
        """
        查询某用户点赞过的帖子(游标分页)

        Args:
            account_id: 目标账户ID
            cursor: 游标(上一页最旧一条的 post_id)
            limit: 每页数量
            viewer_account_id: 当前登录账户ID; 与 account_id 相同才返回私密帖

        Returns:
            list[Post]: 帖子列表
        """
        return await self.dao.get_liked_posts(account_id=account_id, cursor=cursor, limit=limit,
                                              viewer_account_id=viewer_account_id)
