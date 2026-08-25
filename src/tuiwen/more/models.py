from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional, List

from sqlalchemy import BigInteger
from sqlmodel import SQLModel, Field, Column, DateTime, text

from src.tuiwen.core import get_settings

TABLE_PREFIX = get_settings().TABLE_PREFIX

# ------------------------------ IntEnum 整型枚举 ------------------------------
class FeedbackType(IntEnum):
    SUGGESTION = 1  # 功能建议
    BUG = 2         # Bug问题
    COMPLAINT = 3   # 投诉
    OTHER = 4       # 其他


class FeedbackLevel(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3


class FeedbackStatus(IntEnum):
    PENDING = 1      # 待处理
    PROCESSING = 2   # 处理中
    DONE = 3         # 已处理完成
    CLOSED = 4       # 已关闭


# ------------------------------ 前端提交：创建入参模型（父类，公共字段） ------------------------------
class FeedbackCreate(SQLModel):
    """用户提交反馈，仅前端传入字段，作为父类给DB模型继承"""
    content: str = Field(..., description="反馈详细内容", max_length=2000)
    title: Optional[str] = Field(None, description="反馈标题", max_length=256)
    feedback_type: Optional[FeedbackType] = Field(None, description="反馈类型 1建议 2bug 3投诉 4其他")
    level: Optional[FeedbackLevel] = Field(default=FeedbackLevel.NORMAL, description="严重等级 1低 2普通 3高")
    contact: Optional[str] = Field(None, description="联系方式(手机号/邮箱)", max_length=128)
    page_path: Optional[str] = Field(None, description="问题发生页面路由")
    image_urls: Optional[List[str]] = Field(default_factory=list, sa_type="JSON", description="截图图片链接列表")
    app_version: Optional[str] = Field(None, description="应用版本号")
    allow_reply: Optional[bool] = Field(default=True, description="是否允许后台回复联系用户")


# ------------------------------ DB表模型：继承FeedbackCreate，只增加数据库私有字段 ------------------------------
class Feedback(FeedbackCreate, table=True):
    __tablename__ = f"{TABLE_PREFIX}feedback"
    __table_args__ = {"comment": "用户反馈表"}

    id: int = Field(..., primary_key=True, description='表主键ID',
                    sa_column_kwargs={'comment': '表主键ID'}, sa_type=BigInteger)
    account_id: Optional[str] = Field(None, index=True, description="提交用户ID，匿名则为空")

    # 后端从Request获取，前端不传
    user_agent: Optional[str] = Field(None, max_length=1024, description="客户端UA")
    client_ip: Optional[str] = Field(default=None, max_length=64, description="客户端IP")

    # 后台管理字段
    status: FeedbackStatus = Field(default=FeedbackStatus.PENDING, description="状态:1待处理 2处理中 3已完成 4已关闭")
    admin_reply: Optional[str] = Field(default=None, max_length=1024, description="管理员回复内容")
    handle_user_id: Optional[int] = Field(default=None, description="处理管理员ID")

    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                  )
    update_at: datetime = Field(..., default_factory=lambda: datetime.now(timezone.utc), description='最后修改时间',
                                   sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                    onupdate=datetime.now, comment='最后修改时间')
                                   )

# ------------------------------ 返回前端响应模型 ------------------------------
class FeedbackResponse(SQLModel):
    id: int
    account_id: Optional[int]
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
    handle_user_id: Optional[int]
    user_agent: Optional[str]
    client_ip: Optional[str]
    create_at: datetime
    update_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------ 管理员更新反馈模型 ------------------------------
class FeedbackAdminUpdate(SQLModel):
    """管理员处理反馈"""
    status: Optional[FeedbackStatus] = Field(None, description="处理状态 1待处理 2处理中 3已完成 4已关闭")
    admin_reply: Optional[str] = Field(None, description="管理员回复内容", max_length=2000)
