"""关注模型: 关注关系表(tw_follow)与关注统计响应模型。

follower_id(关注者) + followee_id(被关注者) 有联合唯一索引, 保证不重复关注。
"""
import uuid
from datetime import datetime

from pydantic import field_serializer
from sqlalchemy import DateTime, Column, BigInteger, Identity, UUID
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
    follower_id: uuid.UUID = Field(..., index=True, description='关注者账户主键',
                                   sa_column_kwargs={'comment': '关注者账户主键'})
    followee_id: uuid.UUID = Field(..., index=True, description='被关注者账户主键',
                                   sa_column_kwargs={'comment': '被关注者账户主键'})
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False,
                                                   server_default=text("NOW()")))

    # 创建联合索引;
    __table_args__ = (
        Index('idx_follower_followee_unique', 'follower_id', 'followee_id', unique=True),
        {'comment': '关注'},
    )

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class FollowCreate(SQLModel):
    """关注入参 DTO: 只需要「关注谁」。

    NOTE: 入参不要直接用表模型 Follow —— SQLModel 表模型构造时不校验字段类型,
          FastAPI 把 JSON 校验成表模型后, 字符串会原样留在 UUID 字段上,
          直到 model_dump()/写库时才以告警或隐式转换的形式暴露。
    NOTE: follower_id(关注者)由服务端从令牌取, 不接受客户端传入 ——
          否则任何登录用户都能替别人建立关注关系。
    """

    followee_id: uuid.UUID = Field(..., description='被关注者账户主键')


class FollowCountModel(SQLModel):
    """关注主页统计响应: 粉丝数/关注数/是否已关注/获赞数。

    NOTE: 继承 SQLModel(非表模型), 只做响应载体 —— SQLModel 本身即 pydantic BaseModel 子类。
    """
    follower_count: int = Field(0, description='粉丝数')
    followee_count: int = Field(0, description='关注的数量')
    is_following: bool = Field(False, description='当前浏览者是否已关注该账户')
    like_count: int = Field(0, description='获赞数量')
