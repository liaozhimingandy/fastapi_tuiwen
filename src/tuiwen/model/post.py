"""帖子模型: 帖子表(tw_post)、创建入参、权限更新入参及相关枚举。

post_id 采用 uuid7(时间有序), 天然适合按时间游标分页。
"""
from decimal import Decimal
from enum import IntEnum
import uuid
from ipaddress import IPv4Address, IPv6Address
from typing import Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, field_serializer
from sqlalchemy import DateTime, JSON, Column, BigInteger, SMALLINT, Numeric, Identity
from sqlalchemy.dialects.postgresql import INET
from sqlmodel import SQLModel, Field, Index, text

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

class PostType(IntEnum):
    POST = 1         # 普通动态/帖子
    BLOG = 2         # 博客

class RightStatusEnum(IntEnum):
    """帖子权限"""
    PRIVATE = 0
    PUBLIC = 1

    @property
    def label(self):
        mapping = {
            0: "仅自己",
            1: "公开"

        }
        return mapping[self.value]


class PostRightStatusUpdate(SQLModel):

    post_id: UUID = Field(default_factory=uuid.uuid7, index=True, description='帖子ID',
                          sa_column_kwargs={'comment': '帖子ID', "server_default": text("uuidv7()")},
                          unique=True)
    account_id: str = Field(..., index=True, max_length=32, description='用户ID',
                            sa_column_kwargs={'comment': '用户ID'})
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, description='权限状态',
                                          sa_column_kwargs={'comment': '权限状态'},
                                          sa_type=SMALLINT, ge=0)


class PostCreate(PostRightStatusUpdate):
    """发帖入参模型 = 权限三字段 + 内容/来源/位置等业务字段。"""

    class FromDeviceEnum(IntEnum):
        """设备来源类型"""

        WEB = 1
        ANDROID = 2
        IOS = 3
        WINDOWS = 4
        UNKNOWN = 9

        @property
        def label(self):
            mapping = {
                1: "网页版",
                2: "安卓端",
                3: "IOS",
                4: "windows",
                9: "未知"
            }
            return mapping[self.value]

    content: dict = Field(default={}, description='json内容', max_length=1024,
                                 sa_column_kwargs={'comment': '内容'},
                                 sa_type=JSON)
    post_type: PostType = Field(PostType.POST.value, index=True, description="类型",sa_column_kwargs={'comment': '内容类型'},
                                sa_type=SMALLINT, nullable=False, ge=0)
    from_ip: Optional[IPv4Address | IPv6Address] = Field(None, description='来源ip', sa_type=INET(),
                                                         sa_column_kwargs={'comment': '来源ip'})
    from_device: FromDeviceEnum = Field(FromDeviceEnum.UNKNOWN, description='来源设备类型', sa_column_kwargs={'comment': '来源设备类型'},
                                        sa_type=SMALLINT, ge=0)
    location: str | None = Field(None, max_length=64, description='位置', sa_column_kwargs={'comment': '位置'})
    is_top: bool = Field(default=False, description='是否置顶', sa_column_kwargs={'comment': '是否置顶'})
    latitude: Decimal | None = Field(None, sa_type=Numeric(10, 7), description='经度', sa_column_kwargs={'comment': '经度'})
    longitude: Decimal | None = Field(None, sa_type=Numeric(10, 7), description='纬度', sa_column_kwargs={'comment': '纬度'})


class Post(PostCreate, table=True):
    """
    帖子模型

    数据库表 tw_post: 在入参字段之上补充自增主键 id、状态与创建/更新时间;
    create_at/update_at 序列化时统一转配置时区(Asia/Shanghai)。
    """

    __tablename__ = f"{TABLE_PREFIX}post"  # 表名
    __table_args__ = {'comment': '帖子'}  # 表备注

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID",},sa_type=BigInteger,sa_column_args=[Identity(always=False)])
    status: int | None = Field(default=1, description='帖子状态', ge=0,sa_type=SMALLINT, sa_column_kwargs={'comment': '帖子状态'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False,
                                                   server_default=text("NOW()")))
    update_at: datetime = Field(..., default_factory=datetime.now, description='最后修改时间',
                                   sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                    onupdate=datetime.now, comment='最后修改时间')
                                   )

    @field_serializer('create_at', 'update_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)
