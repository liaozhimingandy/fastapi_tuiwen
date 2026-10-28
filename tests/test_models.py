"""表结构约束: 校验「主键 uuid7 化」重构后的不变量。

背景: 早期设计是「自增 bigint 主键 + 业务 ID 唯一索引」双 ID, 两列都唯一但只有
      自增 id 被外键真正引用, 业务 ID 属冗余且会随并发写入产生碰撞风险。
      重构后核心表(account/post/comment/video)统一为单列 uuid7 主键,
      外键表保留自增主键, 但引用列类型必须与之对齐(UUID)。

这些断言不需要连数据库, 直接读 SQLAlchemy 元数据。
"""
import uuid

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
from src.tuiwen.model.video import Video, VideoSource

# 核心表: 主键即业务 ID, 类型 uuid7
CORE_MODELS = [Account, Post, Comment, Video]
# 被移除的冗余业务 ID 列(表名 -> 列名)
REMOVED_COLUMNS = {
    "tw_account": "account_id",
    "tw_post": "post_id",
    "tw_comment": "comment_id",
    "tw_video": "video_id",
}
# 外键列(引用核心表主键) -> 必须与 UUID 主键同类型
UUID_FK_COLUMNS = [
    (Post, "account_id"),
    (Comment, "account_id"),
    (Comment, "obj_id"),
    (Comment, "parent_id"),
    (Video, "account_id"),
    (VideoSource, "video_id"),
    (File, "account_id"),
    (Follow, "follower_id"),
    (Follow, "followee_id"),
    (Like, "obj_id"),
    (Like, "account_id"),
    (Notice, "account_id"),
    (Notice, "target_id"),
    (Notice, "trigger_account_id"),
    (Feedback, "account_id"),
    (Feedback, "handle_user_id"),
]


@pytest.mark.parametrize("model", CORE_MODELS, ids=lambda m: m.__tablename__)
def test_core_table_primary_key_is_uuid(model):
    """核心表主键必须是单列 uuid, 且不会再生成自增序列。"""
    pk_cols = [c for c in model.__table__.columns if c.primary_key]

    assert len(pk_cols) == 1, f"{model.__tablename__} 主键应只有一列: {[c.name for c in pk_cols]}"
    assert pk_cols[0].name == "id"
    assert pk_cols[0].type.python_type is uuid.UUID, f"{model.__tablename__}.id 类型应为 UUID"
    assert pk_cols[0].autoincrement in (False, "auto"), "UUID 主键不应依赖自增"


@pytest.mark.parametrize("table,column", list(REMOVED_COLUMNS.items()))
def test_redundant_business_id_column_removed(table, column):
    """冗余业务 ID 列必须彻底移除, 避免与主键形成两套唯一标识。"""
    model = next(m for m in CORE_MODELS if m.__tablename__ == table)

    assert column not in model.__table__.c, f"{table}.{column} 应已删除(由主键 id 取代)"


@pytest.mark.parametrize("model,column", UUID_FK_COLUMNS, ids=lambda v: getattr(v, "__name__", v))
def test_foreign_key_columns_are_uuid(model, column):
    """引用核心表主键的外键列, 类型必须与主键一致(UUID), 否则跨类型比较会走隐式转换。"""
    col = model.__table__.c.get(column)

    assert col is not None, f"{model.__tablename__}.{column} 不存在"
    assert col.type.python_type is uuid.UUID, (
        f"{model.__tablename__}.{column} 类型应为 UUID, 实际 {col.type}"
    )


def test_log_table_keeps_bigint_identity():
    """日志表属内部运维数据, 不对外暴露, 保留自增主键(不参与 uuid 改造)。"""
    pk = [c for c in Log.__table__.columns if c.primary_key][0]

    assert pk.name == "id"
    assert pk.type.python_type is int
