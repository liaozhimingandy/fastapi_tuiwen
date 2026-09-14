from dal.base import BaseDAO
from notice.models import Notice


class NoticeDAO(BaseDAO[Notice]):
    model = Notice

