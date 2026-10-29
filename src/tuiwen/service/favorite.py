#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： favorite.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/29
    @Desc: 收藏业务服务层 —— 新增 / 取消 / 统计 / 收藏列表
=================================================
"""
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dal.favorite import FavoriteDAO
from src.tuiwen.model.favorite import Favorite
from src.tuiwen.model.post import Post


@dataclass
class FavoriteService:
    """收藏业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: FavoriteDAO

    async def create(self, favorite: Favorite):
        """
        新增一条收藏记录

        Args:
            favorite: 已组装好的收藏实体(target_id / target_type / account_id)

        Returns:
            Favorite: 落库后的收藏实体

        Raises:
            BizError: 409 —— 已经收藏过(靠联合唯一索引兜底)
        """
        try:
            instance = await self.dao.create(favorite)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)
            return instance
        except IntegrityError:
            await self.dao.write_db.rollback()
            raise BizError(code=409, message="已经收藏过了")

    async def delete_favorite(self, target_id: uuid.UUID, account_id: uuid.UUID,
                              target_type: int = Favorite.TargetTypeEnum.POST) -> bool:
        """
        取消当前用户对某对象的收藏

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型

        Returns:
            bool: True 表示确实取消到了记录; False 表示本来就没收藏过
        """
        affected = await self.dao.delete_favorite(target_id=target_id, account_id=account_id,
                                                  target_type=target_type)
        await self.dao.write_db.commit()
        return bool(affected)

    async def get_favorite_count(self, target_id: uuid.UUID, account_id: uuid.UUID,
                                 target_type: int = Favorite.TargetTypeEnum.POST) -> dict:
        """
        查询收藏总数与当前用户是否已收藏

        Args:
            target_id: 目标对象ID
            account_id: 当前登录账户ID
            target_type: 目标对象类型(1帖子/2视频)

        Returns:
            dict: {"favorite_count": int, "is_favorited": bool}
        """
        return await self.dao.get_favorite_count(target_id=target_id, account_id=account_id,
                                                 target_type=target_type)

    async def get_favorited_posts(self, account_id: uuid.UUID, cursor: uuid.UUID | None = None,
                                  limit: int = 10, viewer_account_id: uuid.UUID | None = None) -> list[Post]:
        """
        查询某用户收藏过的帖子(游标分页)

        Args:
            account_id: 目标账户ID
            cursor: 游标(上一页最旧一条的 post_id)
            limit: 每页数量
            viewer_account_id: 当前登录账户ID; 与 account_id 相同才返回私密帖

        Returns:
            list[Post]: 帖子列表
        """
        return await self.dao.get_favorited_posts(account_id=account_id, cursor=cursor, limit=limit,
                                                  viewer_account_id=viewer_account_id)
