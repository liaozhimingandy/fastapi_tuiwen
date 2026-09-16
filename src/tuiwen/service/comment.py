"""
评论业务服务层(CommentService)

职责:
    只做业务编排与参数透传, 真正的数据库操作交给 CommentDAO; 不做事务提交。

分层位置:
    API → CommentService → CommentDAO → PostgreSQL
"""
from dataclasses import dataclass

from src.tuiwen.dal.base import PageResult
from src.tuiwen.dal.comment import CommentDAO
from src.tuiwen.model.comment import Comment


@dataclass
class CommentService:
    """评论业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_comment_service 里是 CommentService(dao=dao))。
    """

    dao: CommentDAO

    async def create(self, comment: Comment):
        """
        新增评论

        Args:
            comment: 已组装好的评论实体(含服务端生成的 comment_id)

        Returns:
            Comment: 落库后的评论实体(未 commit)
        """
        instance = await self.dao.create(comment)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    async def delete(self, comment_id, account_id):
        """
        删除评论(带归属校验)

        Args:
            comment_id: 评论ID
            account_id: 当前登录账户ID, 与 comment_id 共同构成删除条件, 防止越权

        Returns:
            bool: 是否删除到记录
        """
        await self.dao.delete_by_fields(comment_id=comment_id, account_id=account_id)
        await self.dao.write_db.commit()
        return True

    async def get(self, obj_id, obj_type, limit, cursor=None) -> PageResult[Comment]:
        """
        分页查询某目标对象下的评论(游标分页)

        Args:
            obj_id: 目标对象ID(如帖子)
            obj_type: 目标对象类型枚举
            limit: 每页数量
            cursor: 游标, 上一页最旧一条的 comment_id; 为 None 表示查第一页

        Returns:
            PageResult[Comment]: items 评论列表, total 该对象下的评论总数

        说明: 原实现把 UUID 类型的游标当成 offset 传给基类 page(), 基类做 int(offset)
              时会直接抛 TypeError; 这里改用 DAO 的游标分页查询。
        """
        return await self.dao.get_comments_page(obj_id=obj_id, obj_type=obj_type, limit=limit, cursor=cursor)
