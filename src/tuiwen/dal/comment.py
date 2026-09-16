"""
评论数据访问层(CommentDAO)

职责:
    1. 通用 CRUD 复用 BaseDAO(create / partial_update / delete_by_fields 等)
    2. 补充评论列表的「游标分页」查询 —— comment_id 使用 uuid7, 时间有序,
       因此可以直接用 comment_id < cursor 做翻页, 无需 OFFSET

分层位置:
    CommentService → CommentDAO → PostgreSQL

事务原则:
    只执行 SQL, 不主动 commit; 提交时机由上层(Service/API)控制。
"""
import uuid

from sqlmodel import select

from src.tuiwen.dal.base import BaseDAO, PageResult
from src.tuiwen.model.comment import Comment


class CommentDAO(BaseDAO[Comment]):
    model = Comment

    async def get_comments_page(self, obj_id: str, obj_type: int, limit: int = 20,
                                cursor: uuid.UUID | None = None) -> PageResult[Comment]:
        """
        按目标对象分页查询评论(游标分页)

        翻页依据: comment_id(uuid7 时间有序), 取上一页最旧一条的 comment_id 作为游标,
        下一页查询条件为 comment_id < cursor, 结果按 comment_id 倒序。

        相比 OFFSET 分页的优势: 深翻页时不会因前序行扫描而变慢, 且新增评论不会导致漏读/重读。

        Args:
            obj_id: 目标对象ID(如帖子 post_id)
            obj_type: 目标对象类型枚举值
            limit: 每页数量, 会被基类收敛到 [1, MAX_LIMIT]
            cursor: 游标, 上一页最旧一条的 comment_id; 为 None 表示查第一页

        Returns:
            PageResult[Comment]: items 当前页评论, total 该对象下的评论总数(不受游标影响)
        """
        limit, _ = self._safe_page(limit, 0)

        statement = select(Comment).where(Comment.obj_id == obj_id, Comment.obj_type == obj_type)
        if cursor:
            statement = statement.where(Comment.comment_id < cursor)
        # 排序必须写 .desc(): comment_id 是 CHAR(32), 写成 -Comment.comment_id 会被编译成
        # 算术取负 `ORDER BY -comment_id`, 在 PostgreSQL 上是非法运算, 在 SQLite 上恒为 0 导致乱序
        statement = statement.order_by(Comment.comment_id.desc()).limit(limit)
        items = list((await self.exec_read(statement, "get_comments_page")).all())
        # total 表示「该目标对象下的评论总数」, 不带游标条件, 供前端展示总数
        total = await self.count(obj_id=obj_id, obj_type=obj_type)

        return PageResult(items=items, total=total)
