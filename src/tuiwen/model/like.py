"""点赞模型: 点赞关系表(tw_like)与点赞数统计响应模型。

target_type + target_id + account_id 有联合唯一索引, 天然防重复点赞。
"""
import uuid
from enum import IntEnum
from datetime import datetime

from pydantic import field_serializer
from sqlalchemy import DateTime, Column, BigInteger, Identity, UUID
from sqlmodel import SQLModel, Field, Index

from src.tuiwen.model.types import IntEnumType

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


class Like(SQLModel, table=True):
    """点赞数据库表(tw_like)。

    - target_id + target_type: 被赞对象(当前仅帖子)
    - 联合唯一索引同时承担"是否已赞"的判定(查得到=已赞)
    """
    __tablename__ = f"{TABLE_PREFIX}like"  # 表名

    class TargetTypeEnum(IntEnum):
        """点赞对象类别(当前仅支持帖子)。"""
        POST = 1

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    target_id: uuid.UUID = Field(index=True, description='赞对象ID(帖子/评论主键)',
                              sa_column_kwargs={'comment': '赞对象ID(帖子/评论主键)'})
    target_type: TargetTypeEnum = Field(default=TargetTypeEnum.POST, description="点赞对象类别",
                                  sa_column_kwargs={'comment': '点赞对象类别'}, sa_type=IntEnumType(TargetTypeEnum), ge=0)
    account_id: uuid.UUID = Field(..., index=True, description='点赞的用户账户主键',
                                  sa_column_kwargs={'comment': '点赞的用户账户主键'})
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                 comment="创建日期时间", nullable=False))

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)

    # 创建联合索引
    __table_args__ = (
        Index('idx_target_type_target_id_account_id_unique', 'target_type', 'target_id', 'account_id', unique=True),
        Index('idx_target_type_target_id', 'target_type', 'target_id'),
        {'comment': '赞'},
    )


class LikeCreate(SQLModel):
    """点赞入参 DTO。

    NOTE: 入参不要直接用表模型 Like —— SQLModel 表模型不做类型校验, 客户端还能
          顺带伪造 account_id 给别人点赞。点赞人由服务端从令牌取。
    """
    target_id: uuid.UUID = Field(..., description='赞对象ID(帖子主键)')
    target_type: Like.TargetTypeEnum = Field(default=Like.TargetTypeEnum.POST, description='点赞对象类别')


class LikeCountModel(SQLModel):
    """点赞数查询响应: 总数 + 当前用户是否已点赞。

    NOTE: 继承 SQLModel(非表模型), 只做响应载体 —— SQLModel 本身就是 pydantic BaseModel 的子类。
    """
    count: int = Field(0, description='点赞的数量')
    is_liked: bool = Field(False, description='是否已经点赞')
