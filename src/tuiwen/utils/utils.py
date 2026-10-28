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
import re
import secrets
import string
import tomllib
from datetime import datetime

from PIL import Image
from fastapi import UploadFile
from fastapi.routing import APIRoute

from src.tuiwen.core import get_settings
from src.tuiwen.utils.datetime_utils import to_business_tz, utcnow

def get_datetime_now():
    """返回 UTC 当前时间(带 tzinfo)。等价于 datetime_utils.utcnow()。"""
    # 返回当前时间
    return utcnow()


# 创建一个图片类型检查函数
def allowed_file(file: UploadFile, file_type: list[str]) -> bool:
    """用 PIL 探测真实文件格式(而非信任扩展名/Content-Type), 判断是否在允许列表内。

    Args:
        file: 上传文件对象
        file_type: 允许的格式小写列表, 如 ["jpg", "jpeg", "png"]

    Returns:
        bool: 格式合法返回 True; 文件损坏/非图片返回 False
    """
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
    """
    从 pyproject.toml 的 [project] 段读取版本号与描述。
    """
    with open(file_name, "rb") as f:
        data = tomllib.load(f)
    # 假设版本号位于 [tool.poetry] 或 [project] 中
    return data.get("project", {}).get("version"), data.get("project", {}).get("description")


def get_version_from_txt(file_name: str) -> tuple[str, str]:
    """从文本文件首行读取版本号(main.py 用于读 VERSION 文件), 返回 (版本号, 空描述)。"""
    with open(file_name, "r", encoding='utf-8') as f:
        data = f.readline()
    # 假设版本号位于 [tool.poetry] 或 [project] 中
    return data, ""


def get_random_salt(length: int = 6) -> str:
    """
    返回指定长度的salt

    Args:
        length: 长度,默认为6

    Returns:
        字符串salt
    """
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def custom_generate_unique_id(route: APIRoute) -> str:
    """生成 OpenAPI 操作的唯一 id: 「标签名-路由名」, 避免前端代码生成器命名冲突。

    Args:
        route: APIRoute

    Returns:
        路径的唯一标识,字符串

    """
    return f"{route.tags[0]}-{route.name.replace('_', '-')}"


def convert_to_timezone(value: datetime | None) -> datetime | None:
    """【已废弃】把 datetime 转成业务时区; 请改用 datetime_utils.to_business_tz。

    NOTE: 接口返回值**不再**做时区转换 —— 一律给 UTC, 由前端按本地时区渲染。
          本函数只为兼容旧调用点保留, 新代码不要用。
    """
    return to_business_tz(value)


def convert_to_cst_time(dt: datetime) -> datetime | None:
    """【已废弃】把 datetime 转成北京东八时区; 请改用 datetime_utils.to_business_tz。

    NOTE: 同上, 接口返回值不要再用它。

    Args:
        dt (datetime): datetime

    Returns:
        业务时区的 aware 时间

    Examples Usage:
        convert_to_cst_time(datetime.now())

    """
    return to_business_tz(dt)


def hash_password(front_md5: str, salt: str) -> str:
    """密码哈希: 前端传 MD5, 后端再加盐做一次 SHA256, 落库 64 位摘要。

    双重哈希的意义: 即便数据库泄露, 攻击者拿到的是加盐 SHA256,
    无法用彩虹表直接反查前端 MD5, 也无法跨账号复用同一摘要。

    Args:
        front_md5: 前端已计算的 32 位 MD5
        salt: 每账号独立随机盐

    Returns:
        64 位 SHA256 十六进制摘要
    """
    combine = (front_md5 + salt).encode('utf-8')
    return hashlib.sha256(combine).hexdigest()


def create_default_users():
    """批量注册系统预设用户(占位账号): 逐个调用本机注册接口创建。

    用途: 提前占住 root / admin / official 等保留用户名, 防止被普通用户抢注。
    仅在初始化环境手动执行(见文件末尾 __main__), 不属于请求调用链。
    """
    # 局部导入避免 utils 与 logger 在包初始化阶段相互引用; 路径必须写完整的包路径
    from src.tuiwen.utils.logger import logger
    import json
    import urllib.request
    from hashlib import md5
    from urllib.error import HTTPError, URLError

    md5_hash = md5()
    REGISTER_URL = "http://127.0.0.1:8000/api/v2/accounts/register/"  # 改成你的真实接口
    md5_hash.update("".join(random.choices("0123456789", k=6)).encode('utf-8'))  # 足够长的密码
    DEFAULT_PASSWORD = md5_hash.hexdigest()
    # 统一默认信息（所有账号都一样）
    DEFAULT_NICK_NAME = "系统用户"
    DEFAULT_BIRTHDAY = "2026-09-01"
    DEFAULT_AREA_CODE = "CHN"
    DEFAULT_SEX = 0
    DEFAULT_AVATAR = None
    DEFAULT_BIO = "系统预设账号"

    # 关键：用户名 + 邮箱 唯一
    RESERVED_USERNAMES = [
        # System / 系统
        "root",
        "root1",
        "rootuser",
        "system",
        "systemuser",
        "systemaccount",
        "systemadmin",
        "systemadministrator",
        "daemon",
        "nobody",
        "service",
        "serviceuser",
        "serviceaccount",
        "sysadmin",
        "sysop",
        "console",
        "kernel",
        "server",
        "servers",
        "host",
        "hostname",
        "localhost",
        "local",
        "network",
        "networkadmin",
        "backup",
        "cron",
        "tmp",
        "temp",
        "temporary",

        # Admin / 管理员
        "admin",
        "admins",
        "admin1",
        "administrator",
        "administrators",
        "administrator1",
        "superadmin",
        "superadministrator",
        "superuser",
        "operator",
        "operators",
        "manager",
        "managers",
        "moderator",
        "moderators",
        "mod",
        "staff",
        "staffaccount",
        "owner",
        "master",
        "masteradmin",
        "director",
        "executive",
        "president",
        "leader",
        "chief",
        "authority",
        "privileged",
        "privilege",
        "sudo",
        "sudoer",

        # Official / 官方
        "official",
        "officialaccount",
        "officialuser",
        "official-account",
        "verified",
        "verifieduser",
        "verifiedaccount",
        "verified-account",
        "certified",
        "staffofficial",
        "teamofficial",
        "teamaccount",
        "representative",
        "agent",
        "agents",
        "ambassador",

        # Service / 客服
        "support",
        "customersupport",
        "customerservice",
        "customer-service",
        "contact",
        "help",
        "feedback",
        "service",
        "services",
        "assistance",

        # User / 用户
        "user",
        "users",
        "account",
        "accounts",
        "guest",
        "guest1",
        "guestuser",
        "anonymous",
        "anonymoususer",
        "unknown",
        "deleted",
        "deleteduser",
        "deletedaccount",
        "deactivated",
        "disabled",
        "suspended",
        "banned",
        "blocked",
        "inactive",
        "removed",

        # Test / 测试
        "test",
        "test1",
        "testuser",
        "testaccount",
        "testing",
        "tester",
        "testadmin",
        "demo",
        "demo1",
        "demouser",
        "demoaccount",
        "sample",
        "fake",
        "example",
        "exampleuser",
        "exampleaccount",
        "default",
        "defaultuser",
        "defaultaccount",
        "debug",

        # Environment / 环境
        "dev",
        "develop",
        "developer",
        "development",
        "stage",
        "staging",
        "qa",
        "uat",
        "prod",
        "production",

        # Web / Technical / 技术
        "web",
        "www",
        "http",
        "https",
        "httpadmin",
        "httpsadmin",
        "api",
        "apis",
        "apiuser",
        "apikey",
        "rest",
        "graphql",
        "socket",
        "websocket",
        "cdn",
        "dns",
        "domain",
        "domains",
        "backend",
        "frontend",
        "client",
        "clients",
        "app",
        "apps",
        "application",
        "applications",
        "mobile",
        "ios",
        "android",
        "desktop",

        # Database / Infrastructure
        "database",
        "db",
        "dbadmin",
        "postgres",
        "postgresql",
        "mysql",
        "mariadb",
        "redis",
        "mongo",
        "mongodb",
        "elasticsearch",
        "kafka",
        "docker",
        "container",
        "git",
        "ftp",
        "ssh",
        "smtp",
        "mail",
        "email",
        "www-data",
        "nginx",
        "apache",

        # Product / Business / 产品业务
        "product",
        "products",
        "marketing",
        "sales",
        "finance",
        "financial",
        "hr",
        "it",
        "shop",
        "store",
        "market",
        "marketplace",
        "partner",
        "partners",
        "sponsor",
        "sponsors",
        "team",
        "teams",
        "community",
        "blog",
        "news",
        "portal",
        "site",
        "home",
        "index",
        "search",
        "searchbot",

        # Legal / Policy / 法务
        "legal",
        "law",
        "privacy",
        "policy",
        "policies",
        "terms",
        "termsofservice",
        "tos",
        "copyright",
        "dmca",
        "abuse",
        "trust",
        "safety",
        "security",
        "securityadmin",
        "status",
        "statuspage",
        "notice",
        "notices",
        "announcement",
        "announcements",
        "report",
        "reports",
        "moderation",
        "moderationteam",

        # Payment / Finance / 支付金融
        "payment",
        "payments",
        "pay",
        "payout",
        "payouts",
        "deposit",
        "withdraw",
        "withdrawal",
        "wallet",
        "bank",
        "banking",
        "billing",
        "invoice",
        "invoices",
        "refund",
        "refunds",
        "transaction",
        "transactions",
        "checkout",
        "cash",
        "money",
        "currency",
        "coin",
        "coins",
        "token",
        "tokens",
        "crypto",
        "cryptocurrency",
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "usdt",
        "lottery",
        "winner",

        # Membership / VIP
        "free",
        "vip",
        "svip",
        "premium",
        "premiumuser",
        "vipuser",
        "vipaccount",
        "pro",
        "professional",
        "basic",
        "standard",
        "enterprise",
        "business",
        "plus",
        "ultimate",
        "member",
        "membership",
        "subscriber",
        "subscription",
        "trial",
        "freeuser",
        "gold",
        "golduser",
        "diamond",
        "diamonduser",
        "platinum",
        "platinumuser",

        # Security / Hacking
        "hack",
        "hacker",
        "hacking",
        "cracker",
        "exploit",
        "exploiter",
        "rootkit",
        "backdoor",
        "malware",
        "virus",
        "trojan",
        "ransomware",
        "phishing",
        "scam",
        "scammer",
        "fraud",
        "fraudster",
        "spammer",
        "spam",
        "ddos",
        "pentest",
        "pentester",
        "securityresearcher",
        "anon",
        "1337",
        "leet",

        # Common system words / 特殊值
        "null",
        "undefined",
        "none",
        "empty",
        "void",
        "nil",
        "NaN",

        # Common bots / 机器人
        "bot",
        "bots",
        "robot",
        "robots",
        "chatbot",
        "chatbots",
        "searchbot",
        "crawler",
        "crawlerbot",
        "spider",
        "spiderbot",

        # Common app / product terms
        "chat",
        "login",
        "register",
        "registration",
        "signup",
        "signin",
        "password",
        "account",
        "profile",
        "settings",
        "config",
        "configuration",
        "dashboard",
        "control",
        "manager",
        "notification",
        "notifications",

        # Brand / Product specific
        "tuiwen",
        "alsoapp",

        # Common passwords / spam-like names
        "123456",
        "12345678",
        "123456789",
        "888888",
        "88888888",
        "qwerty",
        "qwertyuiop",

        # Offensive / abusive common terms
        "fuck",
        "shit",
    ]
    logger.info("===== 系统预设用户批量注册 =====")
    for username in RESERVED_USERNAMES:
        data = {
            # 注册接口的入参模型(AccountCreate→AccountLogin)
            "mail": f"{username}@alsoapp.com",
            "password": DEFAULT_PASSWORD,
            "username": username,
            "nickname": DEFAULT_NICK_NAME,
            "birthday": DEFAULT_BIRTHDAY,
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

    logger.info(f'执行完毕：成功; 共计{len(RESERVED_USERNAMES)}个')


# 正则规则(用户名黑名单)
REGEX_RULES = [
    # admin_123 root‑001 official88 等保留名变体
    re.compile(r"^(admin|root|bot|official|vip)[_\-\d]", re.IGNORECASE),
    # 零宽隐藏字符绕过，命中直接拒绝
    re.compile(r"[\u2000-\u200f\u2028-\u202f]"),
]

def validate_username(username: str) -> tuple:
    """按黑名单正则校验用户名合法性。

    Args:
        username: 待校验用户名

    Returns:
        (False, 原因) 表示不合法; (True, username) 表示通过
    """
    # 1.正则校验
    for item in REGEX_RULES:
        if item.search(username):
           return False, "用户名包含非法字符或违规变种"
    return True, username


if __name__ == "__main__":
    create_default_users()
