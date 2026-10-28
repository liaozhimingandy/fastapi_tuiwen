#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： test_snap_session_timezone.py
    @Desc: 「天亮即焚」场次窗口的时区口径测试
=================================================

场次规则是「请求方本地时间 23:00 开闸, 次日 06:00 焚毁」。这里锁死四件事:

1. 窗口按**请求方时区**计算: 同一瞬间在不同时区, 可能一边在场次内、一边是白天;
2. `X-Timezone` 缺失或非法(含超长垃圾、注入串)一律回退业务时区, 不抛异常;
3. 夏令时切换后窗口的 UTC 偏移要跟着变 —— 用固定偏移实现会在这里挂掉;
4. 边界: 23:00 整开闸、06:00 整已焚毁。

全部是纯函数用例, 不连数据库, 可在任意机器上秒级跑完。
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.tuiwen import get_settings
from src.tuiwen.service.snap import (
    SNAP_SESSION_BURN_HOUR,
    SNAP_SESSION_OPEN_HOUR,
    current_snap_session,
)

UTC = timezone.utc

#: 北京时间 2026-10-29 23:30, 同时也是纽约时间 2026-10-29 11:30(夏令时 UTC-4)
INSTANT = datetime(2026, 10, 29, 15, 30, tzinfo=UTC)


def _utc(value: datetime) -> datetime:
    """把窗口端点换算成 UTC, 断言时统一口径(避免拿不同 tzinfo 的 aware 时间硬比较)。"""
    return value.astimezone(UTC)


def test_window_hours_are_23_to_6():
    """窗口必须是 23:00~06:00: 前端文案与倒计时都按这个写死, 改了要一起改。"""
    assert (SNAP_SESSION_OPEN_HOUR, SNAP_SESSION_BURN_HOUR) == (23, 6)


def test_shanghai_is_open_at_local_2330():
    """北京时间 23:30 → 窗口 [当天 23:00, 次日 06:00)。"""
    window = current_snap_session(INSTANT, "Asia/Shanghai")
    assert window is not None
    start, end = window
    assert _utc(start) == datetime(2026, 10, 29, 15, 0, tzinfo=UTC)   # 北京 23:00
    assert _utc(end) == datetime(2026, 10, 29, 22, 0, tzinfo=UTC)     # 次日 06:00(北京)


def test_same_instant_is_daytime_in_new_york():
    """同一瞬间在纽约是 11:30, 属于白天 → 没有场次。

    这条是「按用户所在地区判断」的核心: 若固定按北京时间算窗口,
    纽约用户会在当地上午看到"开放中", 而他自己的 23:00 反而是关闭的。
    """
    assert current_snap_session(INSTANT, "America/New_York") is None


def test_new_york_is_open_at_its_own_2330():
    """纽约当地 23:30(EDT, UTC-4) → 窗口同样从当地 23:00 起算。"""
    ny_2330 = datetime(2026, 10, 30, 3, 30, tzinfo=UTC)  # 2026-10-29 23:30 EDT
    window = current_snap_session(ny_2330, "America/New_York")
    assert window is not None
    start, end = window
    assert _utc(start) == datetime(2026, 10, 30, 3, 0, tzinfo=UTC)    # 当地 23:00
    assert _utc(end) == datetime(2026, 10, 30, 10, 0, tzinfo=UTC)     # 当地次日 06:00


@pytest.mark.parametrize("bad_tz", [
    None,                       # 老客户端 / curl 没带这个头
    "",
    "   ",
    "Mars/Base",                # 不存在的时区
    "Asia/Shanghai ",           # 带空白(头里出现空格很常见)
    "A" * 200,                  # 超长垃圾: 不该进入 pytz 查找
    "' OR 1=1 --",              # 注入串
], ids=["none", "empty", "blank", "unknown", "trailing-space", "too-long", "injection"])
def test_bad_timezone_falls_back_to_business_tz(bad_tz):
    """非法时区不抛异常, 回退到业务时区(settings.TIME_ZONE)。"""
    fallback = current_snap_session(INSTANT, get_settings().TIME_ZONE)
    assert current_snap_session(INSTANT, bad_tz) == fallback


def test_missing_timezone_equals_business_tz():
    """不传时区时行为与改动前一致, 不影响老客户端。"""
    assert current_snap_session(INSTANT) == current_snap_session(INSTANT, get_settings().TIME_ZONE)


def test_naive_now_is_interpreted_as_utc():
    """naive 时间按 UTC 解释(全项目统一口径), 不按进程本地时区猜。"""
    naive = datetime(2026, 10, 29, 15, 30)
    assert current_snap_session(naive, "Asia/Shanghai") == current_snap_session(INSTANT, "Asia/Shanghai")


def test_early_morning_belongs_to_last_night():
    """北京时间 05:00 → 仍属于昨夜那一场, 窗口起点是昨天 23:00。"""
    now = datetime(2026, 10, 29, 21, 0, tzinfo=UTC)  # 北京 2026-10-30 05:00
    window = current_snap_session(now, "Asia/Shanghai")
    assert window is not None
    start, end = window
    assert _utc(start) == datetime(2026, 10, 29, 15, 0, tzinfo=UTC)   # 10-29 23:00 北京
    assert _utc(end) == datetime(2026, 10, 29, 22, 0, tzinfo=UTC)     # 10-30 06:00 北京


def test_daytime_has_no_session():
    """北京时间 12:00 → 无场次(内容已焚毁, 下一场未开始)。"""
    now = datetime(2026, 10, 29, 4, 0, tzinfo=UTC)  # 北京 12:00
    assert current_snap_session(now, "Asia/Shanghai") is None


@pytest.mark.parametrize("hour, minute, should_open", [
    (22, 59, False),   # 开闸前一分钟: 白天
    (23, 0, True),     # 开闸时刻(含): 有场次
    (5, 59, True),     # 焚毁前一分钟: 仍有场次
    (6, 0, False),     # 焚毁时刻(不含): 已关闭
], ids=["22:59", "23:00", "05:59", "06:00"])
def test_window_boundaries(hour, minute, should_open):
    """边界: 窗口是 [23:00, 次日 06:00) 左闭右开。"""
    local = datetime(2026, 10, 29, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    window = current_snap_session(local, "Asia/Shanghai")
    assert (window is not None) is should_open


@pytest.mark.parametrize("now_utc, expected_offset", [
    (datetime(2026, 1, 16, 4, 30, tzinfo=UTC), -5),   # 纽约 2026-01-15 23:30 EST
    (datetime(2026, 7, 16, 3, 30, tzinfo=UTC), -4),   # 纽约 2026-07-15 23:30 EDT
], ids=["winter-est", "summer-edt"])
def test_daylight_saving_shifts_window(now_utc, expected_offset):
    """夏令时切换后窗口的 UTC 偏移必须跟着变。

    用「固定 UTC-5」或「写死偏移量」实现的话, 夏天的窗口会整体偏一小时。
    """
    window = current_snap_session(now_utc, "America/New_York")
    assert window is not None
    start, end = window
    assert start.utcoffset() == timedelta(hours=expected_offset)
    assert end.utcoffset() == timedelta(hours=expected_offset)
    assert (start.hour, start.minute) == (23, 0)
    assert (end.hour, end.minute) == (6, 0)
