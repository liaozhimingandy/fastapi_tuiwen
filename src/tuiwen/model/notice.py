#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： notice.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 11:30
    @Desc: 通知/公告模型: 单用户通知与系统公告统一落 tw_notice 表
=================================================
"""
import uuid
from enum import IntEnum

from pydantic import field_serializer
from sqlalchemy import Column, DateTime, text, JSON, BigInteger, Identity, func, UUID
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

from src.tuiwen import get_settings
from src.tuiwen.model.types import IntEnumType
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
    """通知数据库表(tw_notice)。

    设计要点:
    - account_id 为空表示系统公告, 否则是发给单个用户的通知
    - trigger_account_id 记录点赞/评论/关注等动作的触发者(系统通知固定为 1)
    - target_type + target_id 指向关联资源(帖子/评论/用户)
    - target_scope 控制公告推送范围(全部/新用户/VIP)
    - extra 冗余头像/昵称/预览文本, 列表页免联表查询
    - is_deleted 软删除标记
    """
    __tablename__ = f"{TABLE_PREFIX}notice"
    __table_args__ = {'comment': '通知'}

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    # 接收通知的用户
    account_id: Optional[uuid.UUID] = Field(nullable=True, index=True,
                            sa_column_kwargs={'comment': '单用户接收人主键，系统公告为空'})

    # 触发者（点赞/评论/关注的人，系统通知为 None）
    trigger_account_id: Optional[uuid.UUID] = Field(nullable=True, default=None, index=True,
                                           sa_column_kwargs={'comment': '触发者账户主键，系统通知为None'})
    # 字段名用 notice_type 而不是裸 type: `type` 是 Python 内置名, 也是 SQL 保留字,
    # 在 ORM 表达式与手写 SQL 里都容易歧义
    notice_type: NoticeType = Field(default=NoticeType.SYSTEM, nullable=False, ge=0, sa_type=IntEnumType(NoticeType),
                                    index=True, sa_column_kwargs={
            'comment': '通知类型 system系统/like点赞/comment评论/follow关注/mention@'})
    # 关联内容：帖子 / 评论 / 用户 / 其他
    target_type: Optional[NoticeTargetType] = Field(default=None, index=True, sa_type=IntEnumType(NoticeTargetType),
                                                    sa_column_kwargs={'comment': '关联资源类型 post帖子/comment评论/user用户'})
    target_scope: NoticeTargetScope = Field(
        default=NoticeTargetScope.ALL,
        sa_type=IntEnumType(NoticeTargetScope),
        gt=0,
        index=True,
        sa_column_kwargs={'comment': '推送范围 all全部/new新用户/vip付费用户'}
    )
    target_id: Optional[uuid.UUID] = Field(default=None, nullable=True,
                                           index=True, sa_column_kwargs={'comment': '内容主键(帖子/评论/用户)'})

    # 标题、内容
    # NOTE: 点赞/评论/关注类通知不一定有标题, 因此 title 可空;
    #       原写法 `Optional[str] = Field(...)` 是"类型可空但参数必填", 自相矛盾
    title: Optional[str] = Field(default=None, max_length=256, description='标题',
                                 sa_column_kwargs={'comment': '标题'})
    content: dict = Field(..., description='内容', sa_type=JSON, sa_column_kwargs={'comment': '内容'})

    # 扩展字段（存头像、昵称、预览文本，避免联表查询）
    extra: Optional[dict] = Field(default=None, sa_type=JSON, nullable=True,
                                  sa_column_kwargs={'comment': '冗余扩展信息：头像、昵称、预览图'})
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                 sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                  comment="创建日期时间", nullable=False,
                                                  server_default=text("NOW()")))
    # 布尔列, 注释不要再写成 0/1
    is_deleted: bool = Field(
        default=False,
        sa_column_kwargs={'comment': '是否已删除: false正常 / true已删除', "server_default": text("false")}
    )
    # 更新时间
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