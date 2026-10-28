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
        分页查询系统公告(type=SYSTEM)

        Args:
            limit: 每页数量
            offset: 偏移量

        Returns:
            PageResult[Notice]: 公告列表与总数

        NOTE: 未过滤 is_deleted —— 模型上已有软删除标记, 但查询没有带上,
              被"删除"的公告仍会出现在列表里; 同一处的 get_user_notices 也有这个问题
        """
        return await self.dao.page(type=NoticeType.SYSTEM, limit=limit, offset=offset)

    async def get_user_notices(self, account_id: uuid.UUID, limit: int = 10, offset: int = 0):
        """
        分页查询指定用户收到的通知(按创建时间倒序)

        Args:
            account_id: 用户账户ID
            limit: 每页数量
            offset: 偏移量

        Returns:
            PageResult[Notice]: 通知列表与总数

        NOTE: 同样未过滤 is_deleted
        NOTE: 广播类公告(account_id 为空)不会出现在这里 —— 按当前条件用户只能看到
              定向发给自己的通知; 若产品上要求"公告对所有用户可见", 条件需改成
              `account_id == account_id OR account_id IS NULL`, 但 base.page() 只支持
              等值过滤, 得补一个专用查询
        """
        return await self.dao.page(account_id=account_id, limit=limit, offset=offset, order_by=desc(Notice.create_at))
