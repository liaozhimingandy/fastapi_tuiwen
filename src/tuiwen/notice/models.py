#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： models.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 11:30
    @Desc: 
=================================================
"""
from sqlalchemy import Column, DateTime, text, JSON, BigInteger, SmallInteger
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

from src.tuiwen import get_settings

TABLE_PREFIX = get_settings().TABLE_PREFIX


class Notice(SQLModel, table=True):
    __tablename__ = f"{TABLE_PREFIX}notice"
    __table_args__ = {'comment': '通知'}

    id: int = Field(..., primary_key=True, description='表主键ID',
                              sa_column_kwargs={'comment': '表主键ID'}, sa_type=BigInteger)

    # 接收通知的用户
    account_id: str = Field(nullable=True, max_length=32, index=True,
                            sa_column_kwargs={'comment': '单用户接收人ID，系统公告为空'})

    # 触发者（点赞/评论/关注的人，系统通知为 None）
    trigger_account_id: Optional[int] = Field(nullable=True, default=1, index=True,
                                           sa_column_kwargs={'comment': '触发者用户ID，系统通知为1'})
    type: int | None = Field(default=1, nullable=False, sa_type=SmallInteger,
                             index=True, sa_column_kwargs={
            'comment': '通知类型 system系统/like点赞/comment评论/follow关注/mention@'})
    # 关联内容：帖子 / 评论 / 用户 / 其他
    target_type: Optional[str] = Field(default=None, max_length=32, index=True, sa_type=SmallInteger,
                                       sa_column_kwargs={'comment': '关联资源类型 post帖子/comment评论/user用户'})
    target_scope: Optional[int] = Field(
        default=1,
        sa_type=SmallInteger,
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
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                 sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                  comment="创建日期时间", nullable=False,
                                                  server_default=text("NOW()")))
    is_deleted: bool = Field(
        default=False,
        sa_column_kwargs={'comment': '是否已删除 0否 1是'}
    )
    # 更新时间
    updated_at: datetime = Field(..., default_factory=datetime.now, description='最后修改时间',
                                 sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                  onupdate=datetime.now, comment='最后修改时间')
                                 )
