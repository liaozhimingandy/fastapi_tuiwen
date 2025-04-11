#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： models.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/2/22 10:05
    @Desc: 通用模型
=================================================
"""
from datetime import datetime
from typing import TypeVar, Generic, Optional

import pytz
from pydantic import BaseModel
from sqlmodel import Field
from starlette import status

T = TypeVar("T")

class ResponsePublic(BaseModel, Generic[T]):
    code: int = Field(status.HTTP_200_OK, description="响应错误码")
    message: str = Field("success", description="描述信息")
    gmt_created: datetime = Field(default=datetime.now(tz=pytz.timezone("Asia/Shanghai")), description="生成时间")
    data: Optional[T]  = Field(default=None, description="响应数据")
    details: Optional[T] = Field(default=None, description="错误详情")