"""
反馈数据访问层(FeedbackDAO)

职责:
    反馈表无额外专用查询, 直接复用 BaseDAO 提供的通用 CRUD。

分层位置:
    FeedbackService → FeedbackDAO → PostgreSQL
"""
from src.tuiwen.dal.base import BaseDAO
from model.feedback import Feedback


class FeedbackDAO(BaseDAO[Feedback]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Feedback
