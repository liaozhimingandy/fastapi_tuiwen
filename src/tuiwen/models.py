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

import pytz
from pydantic import BaseModel
from sqlmodel import Field
from starlette import status

T = TypeVar("T")

class ResponsePublic(BaseModel, Generic[T]):
    """统一响应包装: code/message/data/details。

    NOTE: gmt_created 用类属性默认值, 在 import 时求值一次后固定,
          所有响应会返回相同的"生成时间"(进程启动时刻), 与预期不符;
          如需真实时间应改为 default_factory=datetime.now
    """
    code: int = Field(status.HTTP_200_OK, description="响应错误码")
    message: str = Field("success", description="描述信息")
    create_at: datetime = Field(default=datetime.now(tz=pytz.timezone("Asia/Shanghai")), description="生成时间")
    data: Optional[T]  = Field(default=None, description="响应数据")
    details: Optional[T] = Field(default=None, description="错误详情")


class PageResponse(BaseModel, Generic[T]):
    """通用列表分页响应模型"""
    items: List[T] = Field(..., description="列表数据")
    total: int = Field(0, description="总记录数")
    page: int = Field(0, description="总页数")
    page_size: int = Field(10, description="每页大小")