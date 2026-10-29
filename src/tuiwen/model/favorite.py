"""收藏模型: 收藏关系表(tw_favorite)与收藏数统计响应模型。

与 tw_like 同构: target_type + target_id + account_id 联合唯一索引, 天然防重复收藏。
"""
import uuid
from enum import IntEnum
from datetime import datetime

from pydantic import field_serializer
from sqlalchemy import Column, BigInteger, Identity
from sqlmodel import SQLModel, Field, Index

from src.tuiwen.model.types import IntEnumType, UTCDateTime

from src.tuiwen.core import get_settings
from src.tuiwen.utils.datetime_utils import to_utc, utcnow

TABLE_PREFIX = get_settings().TABLE_PREFIX


class Favorite(SQLModel, table=True):
    """收藏数据库表(tw_favorite)。

    - target_id + target_type: 被收藏对象(当前仅帖子)
    - 联合唯一索引同时承担"是否已收藏"的判定(查得到=已收藏)
    """
    __tablename__ = f"{TABLE_PREFIX}favorite"  # 表名

    class TargetTypeEnum(IntEnum):
        """收藏对象类别(当前仅支持帖子)。"""
        POST = 1

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    target_id: uuid.UUID = Field(index=True, description='收藏对象ID(帖子主键)',
                                 sa_column_kwargs={'comment': '收藏对象ID(帖子主键)'})
    target_type: TargetTypeEnum = Field(default=TargetTypeEnum.POST, description="收藏对象类别",
                                        sa_column_kwargs={'comment': '收藏对象类别'},
                                        sa_type=IntEnumType(TargetTypeEnum), ge=0)
    account_id: uuid.UUID = Field(..., index=True, description='收藏的用户账户主键',
                                  sa_column_kwargs={'comment': '收藏的用户账户主键'})
    created_at: datetime = Field(..., default_factory=utcnow, description='创建日期时间',
                                 sa_column=Column(UTCDateTime, default=utcnow,
                                                  comment="创建日期时间", nullable=False))

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        return to_utc(value)

    # 创建联合索引
    __table_args__ = (
        Index('idx_fav_target_type_target_id_account_id_unique', 'target_type', 'target_id', 'account_id',
              unique=True),
        Index('idx_fav_target_type_target_id', 'target_type', 'target_id'),
        {'comment': '收藏'},
    )


class FavoriteCreate(SQLModel):
    """收藏入参 DTO。

    NOTE: 入参不要直接用表模型 Favorite —— 表模型不做类型校验, 客户端还能
          顺带伪造 account_id 给别人收藏。收藏人由服务端从令牌取。
    """
    target_id: uuid.UUID = Field(..., description='收藏对象ID(帖子主键)')
    target_type: Favorite.TargetTypeEnum = Field(default=Favorite.TargetTypeEnum.POST, description="收藏对象类别")


class FavoriteCountModel(SQLModel):
    """收藏数查询响应: 总数 + 当前用户是否已收藏。"""
    count: int = Field(0, description='收藏的数量')
    is_favorited: bool = Field(False, description='是否已经收藏')
