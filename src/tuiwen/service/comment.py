"""
评论业务服务层(CommentService)

职责:
    只做业务编排与参数透传, 真正的数据库操作交给 CommentDAO。

事务说明:
    create / delete 在 DAO 执行后自行 commit, 保证调用方拿到的是已落库的数据;
    ⚠️ api/comment.py 在这两个方法之后又调了一次 dao.commit(), 属重复提交(空事务), 无副作用。

分层位置:
    API → CommentService → CommentDAO → PostgreSQL
"""
from dataclasses import dataclass

from src.tuiwen.dal.base import PageResult
from src.tuiwen.dal.comment import CommentDAO
from src.tuiwen.dal.notice import NoticeDAO
from src.tuiwen.dal.post import PostDAO
from src.tuiwen.model.comment import Comment
from src.tuiwen.model.notice import Notice, NoticeType, NoticeTargetType


@dataclass
class CommentService:
    """评论业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_comment_service 里是 CommentService(dao=dao))。

    post_dao / notice_dao 用于评论成功后给帖子作者写一条 COMMENT 通知;
    任一为 None 时跳过(向后兼容, 单测可不注入)。
    TODO: 楼中楼回复父评论作者的回复通知, 后续再补。
    """

    dao: CommentDAO
    post_dao: PostDAO | None = None
    notice_dao: NoticeDAO | None = None

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

        # 评论成功后给帖子作者写一条通知(自己评论自己不通知; 通知失败不影响评论)。
        # 当前只覆盖 target_type=POST; 视频评论的作者反查走 VideoDAO, 后续再补。
        if self.notice_dao is not None and self.post_dao is not None \
                and comment.target_type == Comment.TargetTypeEnum.POST:
            try:
                post = await self.post_dao.get_by_id(comment.target_id)
                if post is not None and post.account_id != comment.account_id:
                    notice = Notice(
                        account_id=post.account_id,
                        trigger_account_id=comment.account_id,
                        notice_type=NoticeType.COMMENT,
                        target_type=NoticeTargetType.POST,
                        target_id=post.id,
                        content={"text": (comment.content or "")[:50]},
                    )
                    await self.notice_dao.create(notice)
                    await self.notice_dao.write_db.commit()
            except Exception:
                await self.notice_dao.write_db.rollback()

        return instance

    async def delete(self, comment_id, account_id):
        """
        删除评论(带归属校验)

        Args:
            comment_id: 评论ID
            account_id: 当前登录账户ID, 与 comment_id 共同构成删除条件, 防止越权

        Returns:
            bool: 是否删除到记录

        NOTE: 这里恒返回 True —— 丢弃了 DAO 的 rowcount。
              评论不存在、或评论不属于该 account_id 时同样是 True, 调用方无法区分;
              API 层返回 204 掩盖了这一点, 但换个返回体就会暴露。
              需要真实结果时把 DAO 的返回值透传出来即可。
        """
        await self.dao.delete_by_fields(id=comment_id, account_id=account_id)
        await self.dao.write_db.commit()
        return True

    async def get(self, target_id, target_type, limit, cursor=None) -> PageResult[Comment]:
        """
        分页查询某目标对象下的评论(游标分页)

        Args:
            target_id: 目标对象ID(如帖子)
            target_type: 目标对象类型枚举
            limit: 每页数量
            cursor: 游标, 上一页最旧一条的 comment_id; 为 None 表示查第一页

        Returns:
            PageResult[Comment]: items 评论列表, total 该对象下的评论总数

        说明: 原实现把 UUID 类型的游标当成 offset 传给基类 page(), 基类做 int(offset)
              时会直接抛 TypeError; 这里改用 DAO 的游标分页查询。
        """
        return await self.dao.get_comments_page(target_id=target_id, target_type=target_type, limit=limit, cursor=cursor)
