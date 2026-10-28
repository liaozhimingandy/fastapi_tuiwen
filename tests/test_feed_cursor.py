"""推荐流游标编解码。

游标是 Base64URL(JSON) 的 opaque 串, 客户端只负责原样回传。这里的用例覆盖:
    - 正常往返(含 uuid7 主键与带时区时间)
    - 被篡改/截断/版本不符时必须收敛成 ValueError(由 Service 转 400)
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.tuiwen.common.feed_cursor import FeedCursor, VideoFeedCursor


def test_roundtrip_preserves_fields():
    feed_id = uuid.uuid7()
    video_id = uuid.uuid7()
    created_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    cursor = FeedCursor.encode(feed_id=feed_id, created_at=created_at, id=video_id)
    decoded = FeedCursor.decode(cursor)

    assert isinstance(decoded, VideoFeedCursor)
    assert decoded.version == FeedCursor.VERSION
    assert decoded.feed_id == feed_id
    assert decoded.id == video_id
    assert decoded.created_at == created_at


def test_cursor_is_url_safe():
    """游标要能直接放进 query string: 不含 '=' 填充与 '+/'(标准 base64 字符)。"""
    cursor = FeedCursor.encode(
        feed_id=uuid.uuid7(),
        created_at=datetime.now(timezone.utc),
        id=uuid.uuid7(),
    )

    assert "=" not in cursor
    assert "+" not in cursor
    assert "/" not in cursor


@pytest.mark.parametrize("bad", ["", "not-base64!!", "eyJ2IjoyfQ"])
def test_invalid_cursor_raises_value_error(bad):
    """非法/版本不符的游标统一抛 ValueError, 不向调用方泄露内部结构。"""
    with pytest.raises(ValueError):
        FeedCursor.decode(bad)


def test_truncated_cursor_raises_value_error():
    cursor = FeedCursor.encode(
        feed_id=uuid.uuid7(),
        created_at=datetime.now(timezone.utc),
        id=uuid.uuid7(),
    )

    with pytest.raises(ValueError):
        FeedCursor.decode(cursor[: len(cursor) // 2])
