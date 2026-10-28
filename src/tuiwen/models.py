#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： models.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/2/22 10:05
    @Desc: 通用响应模型(非表模型): 统一响应包装与分页结构, 供各 API 复用
=================================================
"""
from datetime import datetime
from typing import TypeVar, Generic, Optional, List

from pydantic import BaseModel
from sqlmodel import Field
from starlette import status

from src.tuiwen.utils.datetime_utils import utcnow

T = TypeVar("T")

class ResponsePublic(BaseModel, Generic[T]):
    """统一响应包装: code/message/data/details。

    NOTE: 时间字段叫 timestamp 而不是 created_at —— 它表示"本次响应的生成时间",
          与业务表的 created_at(记录创建时间)不是一回事。
    NOTE: 必须用 default_factory, 写成 `default=datetime.now()` 会在 import 时
          求值一次, 之后所有响应都返回进程启动时刻的时间。
    NOTE: 时间是 UTC(序列化为 ...Z), 由前端按浏览器时区渲染 —— 服务端不再把
          时间预先转成某个固定时区, 否则出国用户看到的永远是北京时间。
    """
    code: int = Field(status.HTTP_200_OK, description="响应错误码")
    message: str = Field("success", description="描述信息")
    timestamp: datetime = Field(default_factory=utcnow, description="响应生成时间(UTC)")
    data: Optional[T]  = Field(default=None, description="响应数据")
    details: Optional[T] = Field(default=None, description="错误详情")


class PageResponse(BaseModel, Generic[T]):
    """通用列表分页响应模型"""
    items: List[T] = Field(..., description="列表数据")
    total: int = Field(0, description="总记录数")
    page: int = Field(0, description="总页数")
    page_size: int = Field(10, description="每页大小")