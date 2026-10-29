"""
通知数据访问层(NoticeDAO)

职责:
    1. 通用 CRUD 复用 BaseDAO(page / create / count)
    2. 批量标记已读(通知中心)

分层位置:
    NoticeService → NoticeDAO → PostgreSQL
"""
from sqlalchemy import update

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.notice import Notice


class NoticeDAO(BaseDAO[Notice]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Notice

    async def mark_read(self, account_id, ids: list[int] | None = None) -> int:
        """把某用户的通知批量标记为已读

        Args:
            account_id: 用户账户ID(只能标自己的, 越权数据不碰)
            ids: 通知主键列表; 为 None/空 时标记该用户全部未读

        Returns:
            int: 实际更新的行数(不 commit, 事务由上层控制)
        """
        stmt = update(Notice).where(
            Notice.account_id == account_id,
            Notice.is_read.is_(False),
            Notice.is_deleted.is_(False),
        )
        if ids:
            stmt = stmt.where(Notice.id.in_(ids))
        stmt = stmt.values(is_read=True)

        result = await self._execute(self.write_db, stmt, op="mark_notices_read")
        return int(result.rowcount or 0)
