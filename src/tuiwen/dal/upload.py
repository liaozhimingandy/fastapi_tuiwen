"""
图片数据访问层(UploadDAO)

职责:
    图片引用表无额外专用查询, 直接复用 BaseDAO 提供的通用 CRUD
    (get_by_unique_field 按 image_md5 去重 / create 登记引用)。

分层位置:
    UploadService → UploadDAO → PostgreSQL
"""
from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.post.models import Image


class UploadDAO(BaseDAO[Image]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Image
