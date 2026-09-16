"""
关注数据访问层(FollowDAO)

职责:
    关注表无额外专用查询, 直接复用 BaseDAO 提供的通用 CRUD
    (create / count / delete_by_fields)。

分层位置:
    FollowService → FollowDAO → PostgreSQL
"""
from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.follow import Follow


class FollowDAO(BaseDAO[Follow]):
    model = Follow
