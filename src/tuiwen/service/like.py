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
            like: 已组装好的点赞实体(obj_id / obj_type / account_id)

        Returns:
            Like: 落库后的点赞实体(未 commit, 事务由上层 API 控制)

        NOTE: 本方法不做重复点赞的前置判断, 靠 tw_like 的联合唯一索引
              (obj_type, obj_id, account_id) 兜底; 重复点赞会抛 IntegrityError,
              而这里没有像 FollowService 那样转 BizError, 最终表现为 500。
              需要在 API 层给出"已点赞"提示的话, 应在此处捕获并转 BizError
        NOTE: api/like.py 直接把表模型 Like 当请求体, 且 model_dump(exclude={}) 不做任何
              排除 —— 客户端可以伪造 account_id 给别人点赞(id/create_at 也会被带进来)。
              应改为从前端只收 obj_id/obj_type, account_id 取 request.state.account_id
        """
        instance = await self.dao.create(like)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    async def like_count(self, obj_id: uuid.UUID):
        """
        统计某帖子的点赞总数

        Args:
            obj_id: 目标对象ID

        Returns:
            int: 点赞总数
        """
        # 仅统计帖子类型(obj_type=POST)的点赞
        return await self.dao.count(obj_type=Like.ObjTypeEnum.POST, obj_id=obj_id)

    async def delete_like(self, obj_id: uuid.UUID, account_id: uuid.UUID):
        """
        取消当前用户对某对象的点赞

        Args:
            obj_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            bool: True 表示确实取消到了记录; False 表示本来就没点过赞

        NOTE: 恒返回 True —— DAO 的 rowcount 被丢掉了, 本来就没点赞也返回成功
        NOTE: 本层与 DAO 都把目标类型写死成 POST(LikeDAO.delete_like 里
              `obj_type == Like.ObjTypeEnum.POST`), 方法签名也没有 obj_type 参数。
              将来支持给评论点赞时, 这里会误删同 obj_id 的帖子点赞记录 ——
              建议现在就把 obj_type 显式提为参数
        """
        await self.dao.delete_like(obj_id=obj_id, account_id=account_id)
        await self.dao.write_db.commit()
        return True

    async def get_like_count(self, obj_id: uuid.UUID, account_id: uuid.UUID):
        """
        查询点赞总数与当前用户是否已点赞

        Args:
            obj_id: 目标对象ID
            account_id: 当前登录账户ID

        Returns:
            dict: {"like_count": int, "is_liked": bool}
        """
        return await self.dao.get_like_count(obj_id=obj_id, account_id=account_id)
