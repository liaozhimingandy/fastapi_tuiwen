"""关注模型: 关注关系表(tw_follow)与关注统计响应模型。

follower_id(关注者) + followee_id(被关注者) 有联合唯一索引, 保证不重复关注。
"""
from datetime import datetime

from pydantic import BaseModel, field_serializer
from sqlalchemy import DateTime, Column, BigInteger,Identity
from sqlmodel import SQLModel, Field, Index, text

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

class Follow(SQLModel, table=True):
    """
    关注模型
    """
    __tablename__ = f"{TABLE_PREFIX}follow"  # 表名

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    follower_id: str = Field(..., index=True, max_length=32, description='关注者',
                             sa_column_kwargs={'comment': '关注者'})
    followee_id: str = Field(..., index=True, max_length=32, description='被关注者',
                             sa_column_kwargs={'comment': '被关注者'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False,
                                                   server_default=text("NOW()")))

    # 创建联合索引;
    __table_args__ = (
        Index('idx_follower_followee_unique', 'follower_id', 'followee_id', unique=True),
        {'comment': '关注'},
    )

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class FollowCountModel(BaseModel):
    """关注主页统计响应: 粉丝数/关注数/是否已关注/获赞数。"""
    follower_count: int = Field(0, description='粉丝数')
    followee_count: int = Field(0, description='关注的数量')
    is_following: bool = Field(False, description='是否正在关注')
    like_count: int = Field(0, description='获赞数量')
