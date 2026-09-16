"""点赞模型: 点赞关系表(tw_like)与点赞数统计响应模型。

obj_type + obj_id + account_id 有联合唯一索引, 天然防重复点赞。
"""
from enum import IntEnum
from datetime import datetime

from pydantic import field_serializer
from sqlalchemy import DateTime, Column, BigInteger, SMALLINT, Identity
from sqlmodel import SQLModel, Field, Index

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


class Like(SQLModel, table=True):
    """点赞数据库表(tw_like)。

    - obj_id + obj_type: 被赞对象(当前仅帖子)
    - 联合唯一索引同时承担"是否已赞"的判定(查得到=已赞)
    """
    __tablename__ = f"{TABLE_PREFIX}like"  # 表名

    class ObjTypeEnum(IntEnum):
        """点赞对象类别(当前仅支持帖子)。"""
        POST = 1

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    obj_id: str = Field(index=True, max_length=36, description='赞对象ID', sa_column_kwargs={'comment': '赞对象ID'})
    obj_type: ObjTypeEnum = Field(default=ObjTypeEnum.POST, description="点赞对象类别",
                                  sa_column_kwargs={'comment': '点赞对象类别'}, sa_type=SMALLINT, ge=0)
    account_id: str = Field(..., index=True, max_length=32, description='点赞的用户',
                            sa_column_kwargs={'comment': '点赞的用户'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                 comment="创建日期时间", nullable=False))

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)

    # 创建联合索引
    __table_args__ = (
        Index('idx_obj_type_obj_id_account_id_unique', 'obj_type', 'obj_id', 'account_id', unique=True),
        Index('idx_obj_type_obj_id', 'obj_type', 'obj_id'),
        {'comment': '赞'},
    )

class LikeCountModel(SQLModel):
    """点赞数查询响应: 总数 + 当前用户是否已点赞。

    NOTE: 这里用的是 pydantic 的 BaseModel(非表模型, 只做响应载体), 没问题;
          但项目里其它响应模型统一走 SQLModel, 建议对齐
    """
    count: int = Field(0, description='点赞的数量')
    is_liked: bool = Field(False, description='是否已经点赞')
