"""帖子模型: 帖子表(tw_post)、创建入参、权限更新入参及相关枚举。

post_id 采用 uuid7(时间有序), 天然适合按时间游标分页。
"""
from decimal import Decimal
from enum import IntEnum
import uuid
from ipaddress import IPv4Address, IPv6Address
from typing import Optional
from datetime import datetime

from pydantic import AliasChoices, field_serializer
from sqlalchemy import DateTime, JSON, Column, BigInteger, SMALLINT, Numeric, Identity, func, UUID
from sqlalchemy.dialects.postgresql import INET
from sqlmodel import SQLModel, Field, Index, text

from src.tuiwen.model.types import IntEnumType
from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

class PostType(IntEnum):
    """内容形态: 普通动态(1) / 博客(2)。"""
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


class PostCreate(SQLModel):
    """发帖入参模型 = 内容/来源/位置等业务字段。

    NOTE: 帖子主键与作者一律由服务端确定, 不在请求体透传:
          - id       : 服务端生成 uuid7(见 Post.id)
          - account_id: 从认证令牌取(request.state.account_id)
          - from_ip  : 从请求上下文取
          原先把 account_id 放在入参里, 客户端可以直接替别人发帖。
    """
    content: dict = Field(default_factory=dict, max_length=1024, description="帖子JSON内容")
    post_type: PostType = Field(default=PostType.POST, ge=0, description="内容类型")
    from_device: FromDeviceEnum = Field(default=FromDeviceEnum.UNKNOWN, ge=0, description="来源设备类型")
    location: Optional[str] = Field(default=None, max_length=64, description="位置文本")
    is_top: bool = Field(default=False, description="是否置顶")
    latitude: Optional[Decimal] = Field(default=None, ge=-90, le=90, description="纬度")
    longitude: Optional[Decimal] = Field(default=None, ge=-180, le=180, description="经度")
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, ge=0, description="权限状态")


class Post(SQLModel, table=True):
    """
    帖子模型

    数据库表 tw_post: 在入参字段之上补充自增主键 id、状态与创建/更新时间;
    created_at/updated_at 序列化时统一转配置时区(Asia/Shanghai)。
    """

    __tablename__ = f"{TABLE_PREFIX}post"  # 表名
    __table_args__ = {'comment': '帖子'}  # 表备注


    # 主键即业务帖子 ID: DB 列名为 id, 对外 JSON 仍沿用 post_id(兼容既有客户端)
    id: uuid.UUID = Field(
        default_factory=uuid.uuid7,
        primary_key=True,
        sa_type=UUID,
        sa_column_kwargs={"comment": "表主键ID (uuid7)", "server_default": text("uuidv7()")},
        serialization_alias="post_id",
        validation_alias=AliasChoices("id", "post_id"),
    )
    content: dict = Field(default={}, description='json内容', max_length=1024,
                          sa_column_kwargs={'comment': '内容'},
                          sa_type=JSON)
    # 默认值必须写枚举成员而不是 .value: 写 PostType.POST.value 会得到一个 int,
    # 序列化时 pydantic 会告警 "Expected `enum` - serialized value may not be as expected"
    post_type: PostType = Field(PostType.POST, index=True, description="类型",
                                sa_column_kwargs={'comment': '内容类型'},
                                sa_type=IntEnumType(PostType), nullable=False, ge=0)
    from_ip: Optional[IPv4Address | IPv6Address] = Field(None, description='来源ip', sa_type=INET(),
                                                         sa_column_kwargs={'comment': '来源ip'})
    from_device: FromDeviceEnum = Field(FromDeviceEnum.UNKNOWN, description='来源设备类型',
                                        sa_column_kwargs={'comment': '来源设备类型'},
                                        sa_type=IntEnumType(FromDeviceEnum), ge=0)
    location: str | None = Field(None, max_length=64, description='位置', sa_column_kwargs={'comment': '位置'})
    is_top: bool = Field(default=False, description='是否置顶', sa_column_kwargs={'comment': '是否置顶'})
    # NOTE: latitude=纬度(南北向, ±90), longitude=经度(东西向, ±180), 描述勿写反
    latitude: Decimal | None = Field(None, sa_type=Numeric(10, 7), description='纬度',
                                     sa_column_kwargs={'comment': '纬度'})
    longitude: Decimal | None = Field(None, sa_type=Numeric(10, 7), description='经度',
                                      sa_column_kwargs={'comment': '经度'})
    account_id: uuid.UUID = Field(..., index=True, description='用户ID(作者主键)',
                            sa_column_kwargs={'comment': '用户ID(作者主键)'})
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, description='权限状态',
                                          sa_column_kwargs={'comment': '权限状态'},
                                          sa_type=IntEnumType(RightStatusEnum), ge=0)
    status: int | None = Field(default=1, description='帖子状态', ge=0,sa_type=SMALLINT, sa_column_kwargs={'comment': '帖子状态'})
    # NOTE: status 目前无任何 Service/DAL 引用, 若用于软删除需先在查询里加过滤条件,
    #       否则列表接口仍会把"已删除"的帖子查出来
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False,
                                                   server_default=text("NOW()")))
    updated_at: datetime = Field(..., default_factory=datetime.now, description="最后更新时间",
                                sa_column=Column(
                                    DateTime(timezone=True),
                                    server_default=func.now(),
                                    onupdate=func.now(),
                                    nullable=False,
                                    comment="最后更新时间"
                                ))

    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class PostRightStatusUpdate(SQLModel):
    """更新帖子可见权限的入参。

    NOTE: 帖子由 URL 路径参数 {post_id} 定位, 作者由认证令牌(request.state.account_id)定位,
          二者已在 API 层用于越权校验, 因此本 DTO 只需携带目标权限状态; 原来的
          post_id / account_id 字段是冗余的(且 post_id 还带了一个不该有的默认值)。
    """
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, description='权限状态')