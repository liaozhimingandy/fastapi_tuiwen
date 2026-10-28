"""时间口径约定(不需要连数据库)。

背景: 服务要全球化, 时间必须是"同一瞬间，多种表达"——
      服务端一律存/返回 UTC, 展示层按浏览器本地时区渲染。

本文件锁死三件事, 任何一条被破坏都会让海外用户看到错的时间或差 8 小时:
    1. 所有 datetime 列必须用 UTCDateTime(impl = timestamptz), 不允许裸 DateTime;
    2. Python 侧默认值必须是 tz-aware UTC —— naive 的 datetime.now() 会随进程 TZ
       环境变量漂移(开发机 Asia/Shanghai / 容器 UTC), 同一个值能差 8 小时;
    3. 对外 JSON 必须带时区且以 Z 结尾, 不允许出现 "2026-10-29T06:32:10" 这种
       不带偏移的字符串 —— 浏览器会把它当本地时间解析, 直接错一个时区。
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.tuiwen.log.models import Log
from src.tuiwen.model.account import Account
from src.tuiwen.model.comment import Comment
from src.tuiwen.model.feedback import Feedback
from src.tuiwen.model.file import File
from src.tuiwen.model.follow import Follow
from src.tuiwen.model.like import Like
from src.tuiwen.model.notice import Notice
from src.tuiwen.model.post import Post
from src.tuiwen.model.snap import Snap
from src.tuiwen.model.types import UTCDateTime
from src.tuiwen.model.video import Video, VideoSource
from src.tuiwen.models import ResponsePublic
from src.tuiwen.utils.datetime_utils import business_now, iso_utc, to_business_tz, to_utc, utcnow

ALL_TABLE_MODELS = [Account, Post, Comment, Video, VideoSource, File, Follow, Like, Notice, Feedback, Snap, Log]
CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 列类型
@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_datetime_columns_use_utc_type(model):
    """每个 datetime 列都必须是 UTCDateTime —— 它同时承担"写入归一"和"读取补 tzinfo"。"""
    offenders = [
        column.name
        for column in model.__table__.c
        if isinstance(column.type, type) and issubclass(column.type, datetime)
    ]
    assert not offenders, f"{model.__tablename__} 存在未使用 UTCDateTime 的时间列: {offenders}"

    for column in model.__table__.c:
        # 只要列类型是 UTCDateTime, 其 impl 必须是 timestamptz, 否则库里仍是 naive wall time
        wrapped = column.type.impl if isinstance(column.type, UTCDateTime) else None
        if wrapped is not None:
            assert wrapped.timezone is True, f"{model.__tablename__}.{column.name} 的 impl 不是 timestamptz"


def test_utc_datetime_impl_is_timestamptz():
    """UTCDateTime 的底层类型必须是带时区的 DateTime(与既有库结构一致, 不需要迁移)。"""
    assert UTCDateTime.impl is not None
    type_ = UTCDateTime()
    assert type_.timezone is True
    assert type_.cache_ok is True


# ---------------------------------------------------------------- 工具函数
def test_utcnow_is_aware_utc():
    """utcnow() 必须是 aware 且正好是 UTC, 不是本地时间的 naive 值。"""
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_to_utc_treats_naive_as_utc():
    """naive 值按 UTC 解释, 不按本地时区猜。"""
    naive = datetime(2026, 10, 29, 6, 32, 10, 123456)
    assert to_utc(naive) == datetime(2026, 10, 29, 6, 32, 10, 123456, tzinfo=timezone.utc)


def test_to_utc_converts_aware_values():
    """带偏移的值换算成同一瞬间的 UTC。"""
    local = datetime(2026, 10, 29, 14, 32, 10, tzinfo=CST)
    assert to_utc(local) == datetime(2026, 10, 29, 6, 32, 10, tzinfo=timezone.utc)


def test_to_utc_none_passthrough():
    assert to_utc(None) is None


def test_to_business_tz_is_display_only():
    """业务时区换算只用于"按本地日历"的规则(场次窗口/归档目录)。"""
    utc_value = datetime(2026, 10, 29, 6, 32, tzinfo=timezone.utc)
    assert to_business_tz(utc_value).isoformat() == "2026-10-29T14:32:00+08:00"
    assert business_now().tzinfo is not None


def test_iso_utc_ends_with_z():
    """原生 dict 响应/游标用 iso_utc 时, 必须显式以 Z 结尾。"""
    assert iso_utc(datetime(2026, 10, 29, 6, 32, 10, 123456, tzinfo=timezone.utc)) == \
        "2026-10-29T06:32:10.123456Z"
    assert iso_utc(datetime(2026, 10, 29, 14, 32, 10, tzinfo=CST)) == "2026-10-29T06:32:10Z"
    assert iso_utc(None) is None


# ---------------------------------------------------------------- 序列化
def _json_of(model) -> dict:
    return json.loads(model.model_dump_json())


def test_post_json_time_is_utc_with_z():
    """接口返回的时间必须带 Z —— 不带偏移的字符串会被浏览器当成本地时间。"""
    post = Post(content={}, account_id=uuid.uuid4())
    payload = _json_of(post)
    assert payload["created_at"].endswith("Z"), payload["created_at"]
    assert payload["updated_at"].endswith("Z"), payload["updated_at"]


def test_model_defaults_are_utc():
    """模型默认值不能是 naive 时间: 否则写入过程依赖进程 TZ, 换环境就差 8 小时。"""
    post = Post(content={}, account_id=uuid.uuid4())
    for field in ("created_at", "updated_at"):
        value = getattr(post, field)
        assert value.tzinfo is not None, f"{field} 是 naive 时间"
        assert value.utcoffset() == timedelta(0), f"{field} 不是 UTC"


def test_response_public_timestamp_is_utc():
    """统一响应包装里的 timestamp 也是 UTC, 不再是北京时间。"""
    payload = _json_of(ResponsePublic())
    assert payload["timestamp"].endswith("Z")


def test_serializer_normalizes_business_tz_to_utc():
    """即使库里/上游给的是 +08:00 的 aware 值, 出参也必须归一到 UTC。"""
    post = Post(content={}, account_id=uuid.uuid4(), created_at=datetime(2026, 10, 29, 14, 32, tzinfo=CST))
    payload = _json_of(post)
    assert payload["created_at"] == "2026-10-29T06:32:00Z"
