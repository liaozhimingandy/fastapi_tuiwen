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

import pytz
from sqlmodel import SQLModel, Field
from starlette import status


class ResponsePublic(SQLModel):
    code: int = Field(status.HTTP_200_OK, description="响应错误码")
    message: str = Field("success", description="描述信息")
    gmt_created: datetime = Field(default=datetime.now(tz=pytz.timezone("Asia/Shanghai")), description="生成时间")
    data: dict | str | None = Field(default=None, description="响应数据")
    details: dict | str | None = Field(default=None, description="错误详情")