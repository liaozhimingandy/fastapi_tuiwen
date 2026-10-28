#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： datetime_utils.py
    @Desc: 统一时间口径 —— 存储与接口输出一律 UTC, 时区换算只发生在展示层
=================================================

约定(前后端共用):
    1. 数据库列一律 timestamptz(带时区), 存进去的是 UTC 时刻;
    2. 进程内 datetime 一律 tz-aware 且为 UTC —— 不再使用 ``datetime.now()`` 这种 naive 值;
    3. 对外 JSON 一律带时区后缀, 形如 ``2026-10-29T06:32:10.123456Z``;
    4. 前端拿到后按浏览器本地时区渲染(见 vue_tuiwen/src/common/datetime.ts)。

为什么不能用 ``datetime.now()``:
    它返回 naive 值, 含义完全取决于**进程的 TZ 环境变量**。asyncpg 对 timestamptz 的
    naive 参数正是按进程本地时区解释的 —— 也就是说同一份代码在开发机(Asia/Shanghai)与
    容器(TZ=UTC)里会写入两个相差 8 小时的时刻, 而这一点在代码和日志里都看不出来。

业务时区(settings.TIME_ZONE)只在这两类场景使用, 不要拿它构造接口返回值:
    - 「按本地日历」判定的业务规则: 快照 23:00~06:00 场次、按年月分目录;
    - 运维排查时想按本地时间看日志。
"""
from datetime import datetime, timezone, tzinfo

import pytz

from src.tuiwen.core import get_settings

#: 全局唯一的 UTC tzinfo(等价于 datetime.timezone.utc, 这里留个别名便于阅读)
UTC = timezone.utc


def utcnow() -> datetime:
    """当前时刻, tz-aware 的 UTC。所有默认值都应改用它。

    Returns:
        datetime: 带 UTC tzinfo 的当前时间

    Examples:
        >>> utcnow().tzinfo is not None
        True
    """
    return datetime.now(UTC)


def to_utc(value: datetime | None) -> datetime | None:
    """把任意 datetime 归一成 tz-aware 的 UTC。

    naive 值一律**按 UTC 解释**, 不按本地时区猜:
    本项目的列都是 timestamptz, 库里存的就是 UTC 时刻, 驱动返回 naive 值时
    只可能是"时区信息丢了", 而不是"变成了本地时间"。

    Args:
        value: 待转换的 datetime, 允许为 None

    Returns:
        datetime | None: UTC 时间; 入参为 None 时返回 None
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def resolve_timezone(name: str | None) -> tzinfo:
    """把 IANA 时区名解析成 tzinfo, 空值或非法值一律回退到业务时区。

    用途: 客户端(浏览器)通过 ``X-Timezone`` 头上报自己的时区, 让「按本地日历判定」
    的业务规则(快照场次)对全球用户都成立 —— 东京用户在东京时间 23:00 看到开闸,
    纽约用户在纽约时间 23:00 看到开闸, 而不是统一按 Asia/Shanghai 的墙钟。

    这个头**来自客户端, 不可信**: 传 ``Mars/Base``、空串、超长垃圾都会走到这里,
    所以只做"尽力解析 + 兜底", 绝不向上抛异常(否则一个畸形请求就能让接口 500)。

    Args:
        name: IANA 时区名, 如 ``Asia/Shanghai``、``America/New_York``; 允许为 None

    Returns:
        tzinfo: 解析成功返回对应时区, 否则返回 settings.TIME_ZONE(默认 Asia/Shanghai)

    Examples:
        >>> resolve_timezone("America/New_York").utcoffset(datetime(2026, 1, 1)).total_seconds()
        -18000.0
    """
    # 时区名最长也就 32 个字符(如 America/Argentina/ComodRivadavia),
    # 放宽到 64; 更长的直接当垃圾丢掉, 不浪费一次 pytz 查找
    cleaned = (name or "").strip()
    if cleaned and len(cleaned) <= 64:
        try:
            return pytz.timezone(cleaned)
        except pytz.UnknownTimeZoneError:
            pass
    return pytz.timezone(get_settings().TIME_ZONE)


def to_business_tz(value: datetime | None) -> datetime | None:
    """转成业务时区(settings.TIME_ZONE, 默认 Asia/Shanghai)。

    仅用于按本地日历判定业务规则的场景(场次窗口、按年月归档),
    不要用它构造接口返回值 —— 接口一律给 UTC。

    Args:
        value: 待转换的 datetime, 允许为 None

    Returns:
        datetime | None: 业务时区的 aware 时间; 入参为 None 时返回 None
    """
    if value is None:
        return None
    if value.tzinfo is None:
        # naive 先按 UTC 补齐, 与 to_utc 保持同一解释, 避免两处口径不一致
        value = value.replace(tzinfo=UTC)
    return value.astimezone(pytz.timezone(get_settings().TIME_ZONE))


def business_now() -> datetime:
    """业务时区的当前时刻(tz-aware), 等价于 ``to_business_tz(utcnow())``。

    Returns:
        datetime: 带业务时区 tzinfo 的当前时间
    """
    return to_business_tz(utcnow())


def iso_utc(value: datetime | None) -> str | None:
    """序列化成 ISO8601 字符串, 统一以 Z 结尾, 例如 ``2026-10-29T06:32:10.123456Z``。

    给不经过 pydantic 的地方用(原生 dict 响应、游标、日志)。
    pydantic 序列化 aware UTC 时本身就会输出 Z, 那里不需要再调本函数。

    Args:
        value: 待序列化的 datetime, 允许为 None

    Returns:
        str | None: ISO8601 字符串; 入参为 None 时返回 None
    """
    dt = to_utc(value)
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")
