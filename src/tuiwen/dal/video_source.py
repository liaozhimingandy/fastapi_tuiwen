#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： video_source.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/1 13:42
    @Desc: 
=================================================
"""
from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.video import VideoSource


class VideoSourceDAO(BaseDAO[VideoSource]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = VideoSource