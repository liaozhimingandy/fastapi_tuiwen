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
import hashlib
import random
import string
import tomllib
from datetime import datetime

from pytz import timezone
from PIL import Image
from fastapi import UploadFile
from fastapi.routing import APIRoute

from src.tuiwen.core import get_settings


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
        file_format = image.format.lower()
        # 检查文件格式是否在允许的格式中
        return file_format in file_type
    except Exception as _:
        # 如果文件不是有效的文件类型，将抛出异常
        return False


# 从pyproject.toml加载应用版本号等信息
def get_version_from_pyproject(file_name: str) -> tuple[str, str]:
    with open(file_name, "rb", encoding='utf-8') as f:
        data = tomllib.load(f)
    # 假设版本号位于 [tool.poetry] 或 [project] 中
    return data.get("project", {}).get("version"), data.get("project", {}).get("description")


def get_version_from_txt(file_name: str) -> tuple[str, str]:
    """从文件中加载版本号"""
    with open(file_name, "r", encoding='utf-8') as f:
        data = f.readline()
    # 假设版本号位于 [tool.poetry] 或 [project] 中
    return data, ""


def get_random_salt(length: int = 8) -> str:
    """
    返回指定长度的salt

    Args:
        length: 长度,默认为8

    Returns:
        字符串salt

    """
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def custom_generate_unique_id(route: APIRoute) -> str:
    """
    自定义生成路径的唯一标识

    Args:
        route: APIRoute

    Returns:
        路径的唯一标识,字符串

    """
    return f"{route.tags[0]}-{route.name.replace('_', '-')}"


def convert_to_cst_time(dt: datetime) -> datetime | None:
    """
    将指定时间对象转成北京东八时区的时间

    Args:
        dt (datetime): datetime

    Returns:
        北京时区的时间字符串

    Examples Usage:
        convert_to_cst_time(datetime.now())

    """
    if dt is not None:
        return dt.astimezone(timezone(get_settings().TIME_ZONE))


def hash_password(front_md5: str, salt: str) -> str:
    """
        前端已经传 MD5 过来
        后端：md5 + salt → 再做一次 SHA256 哈希
        返回64位字符串的密码
        Args:
            front_md5: 前端的md5
            salt: 随机盐

        Returns:
            哈希后的值

        Examples Usage:
            hash_password(a, b)

        """
    combine = (front_md5 + salt).encode('utf-8')
    return hashlib.sha256(combine).hexdigest()


def create_default_users():
    from logger import logger
    import json
    import urllib.request
    from hashlib import md5
    from urllib.error import HTTPError, URLError

    md5_hash = md5()
    REGISTER_URL = "http://127.0.0.1:8000/accounts/register/"  # 改成你的真实接口
    md5_hash.update('admin'.encode('utf-8'))  # 足够长的密码
    DEFAULT_PASSWORD = md5_hash.hexdigest()
    # 统一默认信息（所有账号都一样）
    DEFAULT_NICK_NAME = "系统用户"
    DEFAULT_GMT_BIRTH = "2000-01-01"
    DEFAULT_AREA_CODE = "CHN"
    DEFAULT_SEX = 0
    DEFAULT_AVATAR = "https://picsum.photos/200/200"
    DEFAULT_BIO = "系统预设账号"

    # 关键：用户名 + 邮箱 唯一
    USER_LIST = [
        'tuiwen', 'alsoapp', 'chat','system', 'certified', 'sponsor', 'login', 'abc123', 'admin2024', 'bot', 'web', 'cash', 'user', 'site', 'store', 'shit', 'cracker', 'news', 'demo', 'test', 'administrator', 'sales', 'it', 'contact', 'root', 'billing', 'support', 'daemon', 'account', 'manager', 'free', 'privacy', '88888888', 'sysadmin', 'world', 'terms', 'team', 'owner', 'abc', 'shop', 'god', 'webmaster', 'win', 'superuser', 'diamond', 'root1', 'finance', 'official', 'portal', 'sample', 'backup', 'vip', 'verified', 'help', '123', 'nft', 'blog', 'nobody', 'admin1', 'info', 'register', 'fake', 'users', 'marketing', 'payment', 'guest1', 'hack', 'lottery', 'app', 'admin', 'master', 'hr', 'devil', 'control', 'password', 'community', 'gold', 'crypto', 'hacker', 'hello', 'president', 'fuck', 'service', 'svip', 'qwerty', 'platinum', 'king', 'bitcoin', 'winner', 'queen', 'ass', 'legal', 'premium', 'staff', 'angel', 'mod', 'moderator', '111111', 'feedback', 'money', 'guest', 'ops', 'anonymous', '123456', 'marketplace', 'spam', 'crack', 'product', 'partner', 'elite', 'operator',
    ]
    logger.info("===== 系统预设用户批量注册 =====")
    for username in USER_LIST:
        data = {
            "email": f"{username}@alsoapp.com",
            "password": DEFAULT_PASSWORD,
            "username": username,
            "nick_name": DEFAULT_NICK_NAME,
            "gmt_birth": DEFAULT_GMT_BIRTH,
            "area_code": DEFAULT_AREA_CODE,
            "sex": DEFAULT_SEX,
            "avatar": DEFAULT_AVATAR,
            "bio": DEFAULT_BIO
        }

        data_bytes = json.dumps(data).encode("utf-8")
        r = urllib.request.Request(
            REGISTER_URL,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                status = resp.getcode()
                if 200 <= status < 300:
                    print(f"✅ {username:<12} 注册成功")
                else:
                    print(f"❌ {username:<12} 失败，状态码：{status}")
        except HTTPError as e:
            print(f"❌ {username:<12} HTTP错误：{e.code}")
        except URLError as e:
            print(f"⚠️ {username:<12} 连接失败：{e.reason}")
        except Exception as e:
            print(f"⚠️ {username:<12} 异常：{str(e)}")

    logger.info(f'执行完毕：成功; 共计{len(USER_LIST)}个')


if __name__ == "__main__":
    create_default_users()
