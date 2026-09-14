from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.notice.models import Notice


class NoticeDAO(BaseDAO[Notice]):
    model = Notice

