"""
通知数据访问层(NoticeDAO)

职责:
    通知表无额外专用查询, 直接复用 BaseDAO 提供的通用 CRUD(page / create 等)。

分层位置:
    NoticeService → NoticeDAO → PostgreSQL
"""
from src.tuiwen.dal.base import BaseDAO
from model.notice import Notice


class NoticeDAO(BaseDAO[Notice]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Notice
