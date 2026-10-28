#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： video_source.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/1 13:42
    @Desc: 视频源表 DAO —— 一条视频对应多条清晰度记录(HLS/MP4),
           仅用基类通用 CRUD, 无表专属查询方法
=================================================
"""
from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.video import VideoSource


class VideoSourceDAO(BaseDAO[VideoSource]):
    """视频清晰度资源表的数据访问对象。

    典型用法: 转码完成回调里 bulk_create(各清晰度) → commit;
    推荐流/播放页按 video_id 查全部可用源(需按 quality 排序, 由调用方传 order_by)。
    """
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = VideoSource