from enum import IntEnum
from datetime import datetime

from pydantic import BaseModel, field_serializer
from sqlalchemy import DateTime, Column, BigInteger, SMALLINT, Identity
from sqlmodel import SQLModel, Field, Index

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


class LikeInput(SQLModel):
    """
    赞模型
    """

    class ObjTypeEnum(IntEnum):
        """点赞对象类别(当前仅支持帖子)。"""
        POST = 1

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    obj_id: str = Field(index=True, max_length=36, description='赞对象ID', sa_column_kwargs={'comment': '赞对象ID'})
    obj_type: ObjTypeEnum = Field(default=ObjTypeEnum.POST, description="评论对象类别",
                                  sa_column_kwargs={'comment': '评论对象类别'}, sa_type=SMALLINT, ge=0)
    account_id: str = Field(..., index=True, max_length=32, description='点赞的用户',
                            sa_column_kwargs={'comment': '点赞的用户'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                 comment="创建日期时间", nullable=False))

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class Like(LikeInput, table=True):
    """点赞数据库表(tw_like)。"""
    __tablename__ = f"{TABLE_PREFIX}like"  # 表名

    # 创建联合索引
    __table_args__ = (
        Index('idx_obj_type_obj_id_account_id_unique', 'obj_type', 'obj_id', 'account_id', unique=True),
        Index('idx_obj_type_obj_id', 'obj_type', 'obj_id'),
        {'comment': '赞'},
    )

class LikeCountModel(BaseModel):
    """点赞数查询响应: 总数 + 当前用户是否已点赞。"""
    count: int = Field(0, description='点赞的数量')
    is_liked: bool = Field(False, description='是否已经点赞')
