from dataclasses import dataclass
from sqlmodel import desc, asc
from dal.notice import NoticeDAO
from notice.models import NoticeType, Notice


@dataclass
class NoticeService:
    dao: NoticeDAO

    async def get_system_notices(self, limit: int = 10, offset: int=0):
       return await self.dao.page(type = NoticeType.SYSTEM, limit = limit, offset = offset)

    async def get_user_notices(self, account_id: str, limit: int = 10, offset: int=0):
        return await self.dao.page(account_id=account_id, limit=limit, offset=offset, order_by=desc(Notice.create_at))

