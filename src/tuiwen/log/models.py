#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： account.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/4/3 08:58
    @Desc: 日志表模型(结构化日志落库, 供后台检索与审计)
=================================================
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger
from sqlmodel import SQLModel, Field, Column, DateTime, text, SMALLINT, JSON

from src.tuiwen import get_settings

TABLE_PREFIX = get_settings().TABLE_PREFIX

class Log(SQLModel, table=True):
    """系统运行日志表。

    每条业务/异常事件落一行: app_id 标识来源应用, trace_id 串起一次请求的全链路,
    log_level 沿用标准日志级别数值(TRACE 0 ~ CRITICAL 50), context 存 JSON 上下文。
    """

    __tablename__ = f"{TABLE_PREFIX}log"
    __table_args__ = {'comment': '日志记录信息表'}

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'},
                    sa_type=BigInteger)
    app_id: str = Field(..., description='应用ID,示例:com.alsoapp.esb.api', min_length=5, max_length=32, index=True,
                        sa_column_kwargs={'comment': '应用ID'})
    trace_id: uuid.UUID = Field(..., description='链路ID,用于全链路追踪', index=True, unique=True,
                                sa_column_kwargs={'comment': '链路ID,用于全链路追踪'})
    event_at: datetime = Field(..., description='事件时间', sa_column_kwargs={'comment': '事件时间'})
    event_type: str = Field(..., max_length=64, description='事件类型（如业务操作、错误、调试、警告等）',
                            sa_column_kwargs={'comment': '事件类型'})
    log_level: int = Field(default=20, lt=50, ge=0, description='日志级别(TRACE 0,DEBUG 10,INFO 20,WARN 30,ERROR 40,CRITICAL 50)',
                          index=True, sa_type=SMALLINT, sa_column_kwargs={'comment': '日志级别'})
    message: str = Field(..., max_length=1024, description='日志主要描述信息', sa_column_kwargs={'comment': '日志主要描述信息'})
    context: Optional[dict] = Field(default=None, description='存储额外的上下文和处理细节', sa_type=JSON,
                                    sa_column_kwargs={'comment': '存储额外的上下文和处理细节'})
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), default=datetime.now, comment="创建日期时间",
                                                   nullable=False, server_default=text("NOW()")))


if __name__ == "__main__":
    pass
