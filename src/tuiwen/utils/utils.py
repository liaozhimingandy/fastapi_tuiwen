#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： utils.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/2/12 14:49
    @Desc: 通用工具类
=================================================
"""
import tomllib
import uuid
from datetime import datetime

from pytz import timezone
from PIL import Image
from fastapi import UploadFile
from fastapi.routing import APIRoute

from src.tuiwen.core import settings


def get_datetime_now():
    # 返回当前时间
    return datetime.now(timezone.utc)

# 创建一个图片类型检查函数
def allowed_file(file: UploadFile, file_type: list[str]) -> bool:
    try:
        # 将文件读取为字节流
        image = Image.open(file.file)
        # 在打开文件后，需要将文件指针重置回开头
        file.file.seek(0)
        # 获取文件格式
        file_format = image.format
        # 检查文件格式是否在允许的格式中
        return file_format in file_type
    except Exception as _:
        # 如果文件不是有效的文件类型，将抛出异常
        return False


# 从pyproject.toml加载应用版本号等信息
def get_version_from_pyproject(file_name: str) -> tuple[str, str]:
    with open(file_name, "rb") as f:
        data = tomllib.load(f)
    # 假设版本号位于 [tool.poetry] 或 [project] 中
    return data.get("project", {}).get("version"), data.get("project", {}).get("description")


def get_random_salt(length: int = 8) -> str:
    """
    返回指定长度的salt

    Args:
        length: 长度,默认为8

    Returns:
        字符串salt

    """
    return str(uuid.uuid4().hex[:length])


def custom_generate_unique_id(route: APIRoute) -> str:
    """
    自定义生成路径的唯一标识

    Args:
        route: APIRoute

    Returns:
        路径的唯一标识,字符串

    """
    return f"{route.tags[0]}-{route.name.replace('_', '-')}"


def convert_to_cst_time(time: datetime) -> datetime:
    """
    将指定时间对象转成北京东八时区的时间

    Args:
        time (datetime): datetime

    Returns:
        北京时区的时间字符串

    Examples Usage:
        convert_to_cst_time(datetime.now())

    """
    if time is None:
        time = time.replace(tzinfo=timezone('UTC'))
    return time.astimezone(timezone(settings.TIME_ZONE))


