from datetime import datetime, timezone
from enum import IntEnum, Enum
from typing import Optional, List


from sqlalchemy import BigInteger, JSON, Enum as SaENUM, SMALLINT
from sqlmodel import SQLModel, Field, Column, DateTime, text
from pydantic import field_serializer

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

# ------------------------------ IntEnum 整型枚举 ------------------------------
class FeedbackType(Enum):
    SUGGESTION = 1  # 功能建议
    BUG = 2         # Bug问题
    COMPLAINT = 3   # 投诉
    OTHER = 4       # 其他

    @property
    def label(self):
        mapping = {
            0: "SUGGESTION",
            1: "BUG",
            2: "COMPLAINT",
            9: "OTHER"
        }
        return mapping[self.value]


class FeedbackLevel(Enum):
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


class FeedbackStatus(Enum):
    PENDING = 1      # 待处理
    PROCESSING = 2   # 处理中
    DONE = 3         # 已处理完成
    CLOSED = 4       # 已关闭

    @property
    def label(self):
        mapping = {
            1: "PENDING",
            2: "PROCESSING",
            3: "DONE",
            4: "CLOSED"
        }
        return mapping[self.value]


# ------------------------------ 前端提交：创建入参模型（父类，公共字段） ------------------------------
class FeedbackCreate(SQLModel):
    """用户提交反馈，仅前端传入字段，作为父类给DB模型继承"""
    content: str = Field(..., description="反馈详细内容", max_length=2000, sa_column_kwargs={'comment': '反馈详细内容'})
    title: Optional[str] = Field(None, description="反馈标题", max_length=256, sa_column_kwargs={'comment': '反馈标题'})
    feedback_type: Optional[FeedbackType] = Field(default=FeedbackType.OTHER, sa_type=SaENUM(FeedbackType, values_callable=lambda x: [str(e.value) for e in x]),
                                                  description="反馈类型 1建议 2bug 3投诉 4其他", sa_column_kwargs={'comment': '反馈类型 1建议 2bug 3投诉 4其他'})
    level: Optional[FeedbackLevel] = Field(default=FeedbackLevel.NORMAL, sa_type=SaENUM(FeedbackLevel, values_callable=lambda x: [str(e.value) for e in x]),
                                           description="严重等级 1低 2普通 3高", sa_column_kwargs={'comment': '严重等级 1低 2普通 3高'})
    contact: Optional[str] = Field(None, description="联系方式(手机号/邮箱)", max_length=128, sa_column_kwargs={'comment': '联系方式'})
    page_path: Optional[str] = Field(None, description="问题发生页面路由", sa_column_kwargs={'comment': '问题发生页面路由'})
    image_urls: Optional[List[str]] = Field(default_factory=list, sa_type=JSON, description="截图图片链接列表", sa_column_kwargs={'comment': '截图图片链接列表'})
    app_version: Optional[str] = Field(None, description="应用版本号", sa_column_kwargs={'comment': '应用版本号'})
    allow_reply: Optional[bool] = Field(default=True, description="是否允许后台回复联系用户", sa_column_kwargs={'comment': '是否允许后台回复联系用户'})


# ------------------------------ DB表模型：继承FeedbackCreate，只增加数据库私有字段 ------------------------------
class Feedback(FeedbackCreate, table=True):
    __tablename__ = f"{TABLE_PREFIX}feedback"
    __table_args__ = {"comment": "用户反馈表"}

    id: int = Field(..., primary_key=True, description='表主键ID',
                    sa_column_kwargs={'comment': '表主键ID'}, sa_type=BigInteger)
    account_id: Optional[str] = Field(None, index=True, description="提交用户ID，匿名则为空", sa_column_kwargs={'comment': '用户ID'})

    # 后端从Request获取，前端不传
    user_agent: Optional[str] = Field(None, max_length=1024, description="客户端UA", sa_column_kwargs={'comment': '客户端UA'})
    client_ip: Optional[str] = Field(default=None, max_length=64, description="客户端IP", sa_column_kwargs={'comment': '客户端IP'})

    # 后台管理字段
    status: FeedbackStatus = Field(default=FeedbackStatus.PENDING, sa_type=SaENUM(FeedbackStatus, values_callable=lambda x: [str(e.value) for e in x]), description="状态:1待处理 2处理中 3已完成 4已关闭", sa_column_kwargs={'comment': '状态:1待处理 2处理中 3已完成 4已关闭'})
    admin_reply: Optional[str] = Field(default=None, max_length=1024, description="管理员回复内容", sa_column_kwargs={'comment': '管理员回复内容'})
    handle_user_id: Optional[int] = Field(default=None, description="处理管理员ID", sa_column_kwargs={'comment': '处理管理员ID'})

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


# ------------------------------ 天亮即焚模型 ------------------------------
class EmotionTagEnum(IntEnum):
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


class LateNightPost(SQLModel, table=True):
    __tablename__ = f"{TABLE_PREFIX}night"
    __table_args__ = {"comment": "天亮即焚表"}

    id: int = Field(..., primary_key=True, description='表主键ID',
                    sa_column_kwargs={'comment': '表主键ID'}, sa_type=BigInteger)
    content: dict | None = Field(default={}, description='json内容', max_length=1024,
                                 sa_column_kwargs={'comment': '内容'}, sa_type=JSON)
    emotion: int | None = Field(default=0, sa_type=SMALLINT, ge=0, le=255,
                            sa_column_kwargs={'comment': '情绪标签'}, description="情绪标签编号 1失眠 2委屈 3心动 4放空 5吐槽 6开心")
    topic: str | None = Field(default=None, max_length=64, description="话题编号", sa_column_kwargs={'comment': '话题编号'})
    alias_name: str = Field(..., max_length=32, description="当晚临时代号", sa_column_kwargs={'comment': '当晚临时代号'})
    like: int = Field(default=0, description="点赞数量", sa_column_kwargs={'comment': '点赞数量'})
    from_ip: str | None = Field(None, description='来源ip', max_length=32, sa_column_kwargs={'comment': '来源ip'})
    is_top: bool = Field(default=False, description="是否置顶", sa_column_kwargs={'comment': '是否置顶'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                 comment='创建日期时间', nullable=False, server_default=text("NOW()"))
                                )

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class LateNightLeaveCreate(SQLModel):
    content: dict = Field(..., max_length=512, description='内容')
    emotion: int | None = Field(default=None, description="情绪标签编号 1失眠 2委屈 3心动 4放空 5吐槽 6开心")
    topic: str | None = Field(default=None, description="话题编号")
    alias_name: str = Field(..., max_length=32, description="当晚临时代号")


