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

from PIL import Image
from fastapi import UploadFile
from fastapi.routing import APIRoute


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
    """返回指定长度的salt"""
    return str(uuid.uuid4().hex[:length])


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"
