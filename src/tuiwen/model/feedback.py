"""用户反馈模型: 反馈表(tw_feedback)、创建/管理端入参与响应模型。"""
from datetime import datetime, timezone
from enum import IntEnum
from ipaddress import IPv4Address, IPv6Address
from typing import Optional, List

from sqlalchemy import BigInteger, JSON, SMALLINT, Identity
from sqlmodel import SQLModel, Field, Column, DateTime, text
from sqlalchemy.dialects.postgresql import INET
from pydantic import field_serializer

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

# ------------------------------ IntEnum 整型枚举 ------------------------------
class FeedbackType(IntEnum):
    """反馈类型: 1建议 2Bug 3投诉 4其他。"""
    SUGGESTION = 1  # 功能建议
    BUG = 2         # Bug问题
    COMPLAINT = 3   # 投诉
    OTHER = 4       # 其他

    @property
    def label(self):
        mapping = {
            1: "SUGGESTION",
            2: "BUG",
            3: "COMPLAINT",
            4: "OTHER"
        }
        return mapping[self.value]


class FeedbackLevel(IntEnum):
    """反馈严重等级: 1低 2普通 3高。"""
    LOW = 1
    NORMAL = 2
    HIGH = 3

    @property
    def label(self):
        mapping = {
            1: "LOW",
            2: "NORMAL",
            3: "HIGH"
        }
        return mapping[self.value]


class FeedbackStatus(IntEnum):
    """处理状态流转: PENDING(1) → PROCESSING(2) → DONE(3); CLOSED(0) 表示关闭。"""
    PENDING = 1      # 待处理
    PROCESSING = 2   # 处理中
    DONE = 3         # 已处理完成
    CLOSED = 0       # 已关闭

    @property
    def label(self):
        mapping = {
            1: "PENDING",
            2: "PROCESSING",
            3: "DONE",
            0: "CLOSED"
        }
        return mapping[self.value]


# ------------------------------ 前端提交：创建入参模型（父类，公共字段） ------------------------------
class FeedbackCreate(SQLModel):
    """用户提交反馈入参DTO：仅做参数校验，不映射数据库表"""
    content: str = Field(..., max_length=2000, description="反馈详细内容")
    title: Optional[str] = Field(None, max_length=256, description="反馈标题")
    feedback_type: FeedbackType = Field(default=FeedbackType.OTHER, description="反馈类型：1建议 2bug 3投诉 4其他")
    level: FeedbackLevel = Field(default=FeedbackLevel.NORMAL, description="严重等级：1低 2普通 3高")
    contact: Optional[str] = Field(None, max_length=128, description="联系方式(手机号/邮箱)")
    page_path: Optional[str] = Field(None, description="问题发生页面路由")
    image_urls: List[str] = Field(default_factory=list, description="截图图片链接列表")
    app_version: Optional[str] = Field(None, description="应用版本号")
    allow_reply: bool = Field(default=True, description="是否允许后台回复联系用户")


# ------------------------------ DB表模型：字段与 FeedbackCreate 对齐, 另增服务端/管理端字段 ------------------------------
class Feedback(SQLModel, table=True):
    """反馈数据库表(tw_feedback)。

    NOTE: 基类必须是 SQLModel —— 换成 pydantic(含 pydantic.v1) 的 BaseModel 时,
          `table=True` 会与 Pydantic 元类冲突, 导入即 RecursionError/TypeError。

    与 FeedbackCreate 的关系: 业务字段逐一对齐(未用继承, 便于各自加 nullable/索引),
    在此之上补充三类字段:
    - 服务端补全: account_id / user_agent / from_ip(来自请求上下文, 前端不传)
    - 管理端: status / admin_reply / handle_user_id(后台处理流转用)
    - 时间: create_at / update_at
    """

    __tablename__ = f"{TABLE_PREFIX}feedback"
    __table_args__ = {"comment": "用户反馈表"}

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    content: str = Field(..., description="反馈详细内容", max_length=2000, sa_column_kwargs={'comment': '反馈详细内容'})
    title: Optional[str] = Field(None, description="反馈标题", max_length=256, sa_column_kwargs={'comment': '反馈标题'})
    feedback_type: Optional[FeedbackType] = Field(default=FeedbackType.OTHER, sa_type=SMALLINT,
                                                  description="反馈类型 1建议 2bug 3投诉 4其他",
                                                  sa_column_kwargs={'comment': '反馈类型 1建议 2bug 3投诉 4其他'})
    level: Optional[FeedbackLevel] = Field(default=FeedbackLevel.NORMAL, sa_type=SMALLINT,
                                           description="严重等级 1低 2普通 3高",
                                           sa_column_kwargs={'comment': '严重等级 1低 2普通 3高'})
    contact: Optional[str] = Field(None, description="联系方式(手机号/邮箱)", max_length=128,
                                   sa_column_kwargs={'comment': '联系方式'})
    page_path: Optional[str] = Field(None, description="问题发生页面路由",
                                     sa_column_kwargs={'comment': '问题发生页面路由'})
    image_urls: Optional[List[str]] = Field(default_factory=list, sa_type=JSON, description="截图图片链接列表",
                                            sa_column_kwargs={'comment': '截图图片链接列表'})
    app_version: Optional[str] = Field(None, description="应用版本号", sa_column_kwargs={'comment': '应用版本号'})
    allow_reply: Optional[bool] = Field(default=True, description="是否允许后台回复联系用户",
                                        sa_column_kwargs={'comment': '是否允许后台回复联系用户'})
    account_id: Optional[str] = Field(None, index=True, description="提交用户ID，匿名则为空", sa_column_kwargs={'comment': '用户ID'})

    # 后端从Request获取，前端不传
    user_agent: Optional[str] = Field(None, max_length=1024, description="客户端UA", sa_column_kwargs={'comment': '客户端UA'})
    from_ip: Optional[IPv4Address | IPv6Address] = Field(None, description='来源ip', sa_type=INET(), sa_column_kwargs={'comment': '来源ip'})
    # 后台管理字段
    status: FeedbackStatus = Field(default=FeedbackStatus.PENDING, sa_type=SMALLINT, description="状态:0已关闭 1待处理 2处理中 3已完成", sa_column_kwargs={'comment': '状态:0已关闭 1待处理 2处理中 3已完成'})
    admin_reply: Optional[str] = Field(default=None, max_length=1024, description="管理员回复内容", sa_column_kwargs={'comment': '管理员回复内容'})
    handle_user_id: Optional[str] = Field(default=None, max_length=32, description="处理管理员ID", sa_column_kwargs={'comment': '处理管理员ID'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                  )
    update_at: datetime = Field(..., default_factory=lambda: datetime.now(timezone.utc), description='最后修改时间',
                                   sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                    onupdate=datetime.now, comment='最后修改时间')
                                   )

    @field_serializer('create_at', 'update_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


# ------------------------------ 返回前端响应模型 ------------------------------
class FeedbackResponse(SQLModel):
    """反馈详情响应模型(from_attributes 支持 ORM 对象直接转换)。
    """
    id: int
    account_id: Optional[str]
    title: Optional[str]
    content: str
    feedback_type: Optional[FeedbackType]
    level: FeedbackLevel
    contact: Optional[str]
    page_path: Optional[str]
    image_urls: List[str]
    app_version: Optional[str]
    allow_reply: bool
    status: FeedbackStatus
    admin_reply: Optional[str]
    # NOTE: 处理人ID与表模型 handle_user_id 一致都是字符串账户ID, 不要写成 int
    handle_user_id: Optional[str]
    user_agent: Optional[str]
    create_at: datetime
    update_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------ 管理员更新反馈模型 ------------------------------
class FeedbackAdminUpdate(SQLModel):
    """管理员处理反馈"""
    status: Optional[FeedbackStatus] = Field(None, description="处理状态 0已关闭 1待处理 2处理中 3已完成")
    admin_reply: Optional[str] = Field(None, description="管理员回复内容", max_length=2000)

