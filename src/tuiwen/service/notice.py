"""
通知业务服务层(NoticeService)

职责:
    1. 分页查询系统公告类通知
    2. 分页查询指定用户收到的通知

分层位置:
    API → NoticeService → NoticeDAO → PostgreSQL
"""
import uuid
from dataclasses import dataclass
from sqlmodel import desc
from src.tuiwen.dal.notice import NoticeDAO
from src.tuiwen.model.notice import NoticeType, Notice


@dataclass
class NoticeService:
    """通知业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: NoticeDAO

    async def get_system_notices(self, limit: int = 10, offset: int = 0):
        """
        分页查询系统公告(notice_type=SYSTEM)

        Args:
            limit: 每页数量
            offset: 偏移量

        Returns:
            PageResult[Notice]: 公告列表与总数

        说明: 必须带上 is_deleted=False —— 模型上有软删除标记, 过滤条件漏掉
              会让"已删除"的公告继续出现在列表里。
        """
        return await self.dao.page(notice_type=NoticeType.SYSTEM, is_deleted=False,
                                   limit=limit, offset=offset, order_by=desc(Notice.created_at))

    async def get_user_notices(self, account_id: uuid.UUID, limit: int = 10, offset: int = 0,
                               notice_type: NoticeType | int | None = None):
        """
        分页查询指定用户收到的通知(按创建时间倒序)

        Args:
            account_id: 用户账户ID
            limit: 每页数量
            offset: 偏移量
            notice_type: 通知类型过滤(NoticeType); None 表示不过滤(全部)

        Returns:
            PageResult[Notice]: 通知列表与总数

        NOTE: 广播类公告(account_id 为空)不会出现在这里 —— 按当前条件用户只能看到
              定向发给自己的通知; 若产品上要求"公告对所有用户可见", 条件需改成
              `account_id == account_id OR account_id IS NULL`, 但 base.page() 只支持
              等值过滤, 得补一个专用查询
        """
        filters: dict = {"account_id": account_id, "is_deleted": False}
        if notice_type is not None:
            filters["notice_type"] = notice_type
        return await self.dao.page(**filters,
                                   limit=limit, offset=offset, order_by=desc(Notice.created_at))

    async def unread_count(self, account_id: uuid.UUID) -> int:
        """
        统计指定用户的未读通知数

        Args:
            account_id: 用户账户ID

        Returns:
            int: 未读数
        """
        return await self.dao.count(account_id=account_id, is_read=False, is_deleted=False)

    async def mark_read(self, account_id: uuid.UUID, ids: list[int] | None = None) -> int:
        """
        批量标记通知为已读

        Args:
            account_id: 用户账户ID(只能标自己的)
            ids: 通知主键列表; None/空 表示全部标记已读

        Returns:
            int: 实际标记的行数
        """
        affected = await self.dao.mark_read(account_id, ids=ids)
        await self.dao.write_db.commit()
        return affected
