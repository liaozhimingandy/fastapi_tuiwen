#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： account.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 11:30
    @Desc: 
=================================================
"""
from enum import IntEnum

from pydantic import field_serializer
from sqlalchemy import Column, DateTime, text, JSON, BigInteger, SmallInteger, Identity
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

from src.tuiwen import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

class NoticeType(IntEnum):
    """通知类型"""
    SYSTEM = 0      # 系统通知
    LIKE = 1        # 点赞
    COMMENT = 2     # 评论
    FOLLOW = 3      # 关注
    MENTION = 4     # @提及

class NoticeTargetType(IntEnum):
    """通知‑关联资源类型"""
    POST = 1        # 帖子
    COMMENT = 2     # 评论
    USER = 3        # 用户

class NoticeTargetScope(IntEnum):
    """通知‑推送范围"""
    ALL = 1         # 全部用户
    NEW_USER = 2    # 新用户
    VIP = 3         # 付费VIP用户


class Notice(SQLModel, table=True):
    __tablename__ = f"{TABLE_PREFIX}notice"
    __table_args__ = {'comment': '通知'}

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    # 接收通知的用户
    account_id: str = Field(nullable=True, max_length=32, index=True,
                            sa_column_kwargs={'comment': '单用户接收人ID，系统公告为空'})

    # 触发者（点赞/评论/关注的人，系统通知为 None）
    trigger_account_id: Optional[str] = Field(nullable=True, default=1, index=True, max_length=32,
                                           sa_column_kwargs={'comment': '触发者用户ID，系统通知为1'})
    type: NoticeType | None = Field(default=NoticeType.SYSTEM, nullable=False, ge=0, sa_type=SmallInteger,
                             index=True, sa_column_kwargs={
            'comment': '通知类型 system系统/like点赞/comment评论/follow关注/mention@'})
    # 关联内容：帖子 / 评论 / 用户 / 其他
    target_type: Optional[NoticeTargetType] = Field(default=None, index=True, sa_type=SmallInteger,
                                       sa_column_kwargs={'comment': '关联资源类型 post帖子/comment评论/user用户'})
    target_scope: NoticeTargetScope = Field(
        default=1,
        sa_type=SmallInteger,
        gt=0,
        index=True,
        sa_column_kwargs={'comment': '推送范围 all全部/new新用户/vip付费用户'}
    )
    target_id: Optional[str] = Field(default=None, max_length=32, nullable=True,
                                     index=True, sa_column_kwargs={'comment': '内容ID'})

    # 标题、内容
    title: Optional[str] = Field(..., max_length=256, description='标题', sa_column_kwargs={'comment': '标题'})
    content: dict = Field(..., description='内容', sa_type=JSON, sa_column_kwargs={'comment': '内容'})

    # 扩展字段（存头像、昵称、预览文本，避免联表查询）
    extra: Optional[dict] = Field(default=None, sa_type=JSON, nullable=True,
                                  sa_column_kwargs={'comment': '冗余扩展信息：头像、昵称、预览图'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                 sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                  comment="创建日期时间", nullable=False,
                                                  server_default=text("NOW()")))
    is_deleted: bool = Field(
        default=False,
        sa_column_kwargs={'comment': '是否已删除 0否 1是'}
    )
    # 更新时间
    update_at: datetime = Field(..., default_factory=datetime.now, description='最后修改时间',
                                 sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                  onupdate=datetime.now, comment='最后修改时间')
                                 )

    @field_serializer('create_at', 'update_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)