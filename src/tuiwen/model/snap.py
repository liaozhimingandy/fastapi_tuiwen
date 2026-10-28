"""天亮即焚(匿名树洞)模型: snap 表(tw_snap)与发布入参。

内容匿名展示(alias_name 为当晚临时代号), 带情绪标签与话题,
点赞数直接冗余在表上, 由 SQL 原子自增维护。
"""
from datetime import datetime
from enum import IntEnum
from ipaddress import IPv4Address, IPv6Address
from typing import Optional

from sqlalchemy import BigInteger, JSON, Identity
from sqlmodel import SQLModel, Field, Column, text
from sqlalchemy.dialects.postgresql import INET
from pydantic import field_serializer

from src.tuiwen.model.types import IntEnumType, UTCDateTime
from src.tuiwen.core import get_settings
from src.tuiwen.utils.datetime_utils import to_utc, utcnow
TABLE_PREFIX = get_settings().TABLE_PREFIX

# ------------------------------ 天亮即焚模型 ------------------------------
class EmotionTagEnum(IntEnum):
    """情绪标签编号(与前端约定一致, 落库时只存编号)。"""
    NONE = 0        # 未选择情绪
    INSOMNIA = 1    # 失眠
    WRONGED = 2     # 委屈
    HEARTBEAT = 3   # 心动
    RELAX = 4       # 放空
    COMPLAIN = 5    # 吐槽
    HAPPY = 6       # 开心

    SAD = 7         # 难过
    LONELY = 8      # 孤独
    ANXIOUS = 9     # 焦虑
    CONFUSED = 10   # 迷茫
    ANGRY = 11      # 生气
    TIRED = 12      # 疲惫
    TOUCHED = 13    # 感动
    GUILTY = 14     # 愧疚
    HOPEFUL = 15    # 抱有期待


class Snap(SQLModel, table=True):
    """天亮即焚数据库表(tw_snap)。

    - content: JSON 内容体
    - emotion: 情绪标签编号(见 EmotionTagEnum)
    - alias_name: 当晚匿名临时代号(必填)
    - like_count: 点赞数冗余字段, 由 DAL 用 SQL 原子自增维护。
      字段名不能叫 like —— LIKE 是 SQL 保留字, 手写 SQL 时必须加引号,
      在 ORM 表达式里也容易和 `.like()` 运算符混淆
    - from_ip: 来源 IP(INET 类型)
    """
    __tablename__ = f"{TABLE_PREFIX}snap"
    __table_args__ = {"comment": "天亮即焚表"}

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    # 默认值必须用 default_factory: 直接写 default={} 会让所有实例共享同一个 dict
    content: dict | None = Field(default_factory=dict, description='json内容', max_length=1024,
                                 sa_column_kwargs={'comment': '内容'}, sa_type=JSON)
    emotion: EmotionTagEnum | None = Field(default=EmotionTagEnum.NONE, sa_type=IntEnumType(EmotionTagEnum), ge=0, le=255,
                                           sa_column_kwargs={'comment': '情绪标签 0未选 1失眠 ... 15期待'},
                                           description="情绪标签编号, 取值见 EmotionTagEnum")
    topic: str | None = Field(default=None, max_length=64, description="话题编号", sa_column_kwargs={'comment': '话题编号'})
    alias_name: str = Field(..., max_length=32, description="当晚临时代号", sa_column_kwargs={'comment': '当晚临时代号'})
    like_count: int = Field(default=0, description="点赞数量", sa_column_kwargs={'comment': '点赞数量'})
    from_ip: Optional[IPv4Address | IPv6Address] = Field(None, description='来源ip', sa_type=INET(), sa_column_kwargs={'comment': '来源ip'})
    is_top: bool = Field(default=False, description="是否置顶", sa_column_kwargs={'comment': '是否置顶'})
    created_at: datetime = Field(..., default_factory=utcnow, description='创建日期时间',
                                sa_column=Column(UTCDateTime, default=utcnow,
                                                 comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                )

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        return to_utc(value)


class SnapCreate(SQLModel):
    """发布天亮即焚的入参模型(仅业务字段, 不含 IP/点赞数等服务端字段)。"""
    content: dict = Field(..., max_length=512, description='内容')
    emotion: EmotionTagEnum | None = Field(default=None, description="情绪标签编号, 取值见 EmotionTagEnum")
    topic: str | None = Field(default=None, description="话题编号")
    alias_name: str = Field(..., max_length=32, description="当晚临时代号")


