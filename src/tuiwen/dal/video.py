from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.video import Video


class VideoDAO(BaseDAO[Video]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Video
