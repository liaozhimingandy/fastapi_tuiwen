"""对外 JSON 契约: 主键在响应里仍叫 account_id / post_id / comment_id / video_id。

重构把库内列名统一成 id, 但客户端的字段名不能跟着改名 —— 否则前端、App 与
第三方全部要同步发版。这里通过 pydantic 的序列化别名把两者解耦, 并加断言锁住。
"""
import uuid

from src.tuiwen.model.account import Account, AccountInfo
from src.tuiwen.model.comment import Comment
from src.tuiwen.model.post import Post
from src.tuiwen.model.video import Video


def test_account_serializes_as_account_id():
    """库内列 id -> 响应字段 account_id, 且不额外暴露 id。"""
    account = Account(username="tester")
    data = account.model_dump(mode="json", by_alias=True)

    assert "account_id" in data
    assert "id" not in data
    assert uuid.UUID(data["account_id"])


def test_post_serializes_as_post_id():
    post = Post(account_id=uuid.uuid7())
    data = post.model_dump(mode="json", by_alias=True)

    assert "post_id" in data
    assert "id" not in data


def test_comment_serializes_as_comment_id():
    comment = Comment(content="hi", account_id=uuid.uuid7(), target_id=uuid.uuid7())
    data = comment.model_dump(mode="json", by_alias=True)

    assert "comment_id" in data
    assert "id" not in data


def test_video_serializes_as_video_id():
    video = Video(account_id=uuid.uuid7(), video_md5="0" * 32)
    data = video.model_dump(mode="json", by_alias=True)

    assert "video_id" in data
    assert "id" not in data


def test_account_info_reads_orm_attribute():
    """响应 DTO 从 ORM 实例取值时, 别名要能读到 id 列(而不是错误的同名属性)。"""
    account = Account(username="tester")
    info = AccountInfo.model_validate(account)

    assert info.id == account.id
    assert info.model_dump(mode="json", by_alias=True)["account_id"] == str(account.id)
