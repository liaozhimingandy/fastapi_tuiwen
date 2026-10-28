"""字段命名与入参 DTO 的约定(不需要连数据库)。

覆盖两类问题:
    1. 列名约定 —— 时间列统一 created_at/updated_at, 不再出现 create_at/update_at、
       nick_name、gmt_birth、Snap.like(与 SQL 保留字冲突)、裸 type 等含糊命名;
    2. 入参 DTO —— 创建类接口的请求体绝不允许携带 account_id / follower_id 这类
       身份字段, 否则客户端能替别人发帖、评论、点赞、关注。

改动模型或接口时如果碰了这些地方, 这里会直接失败, 比翻 OpenAPI 更早暴露问题。
"""
import enum
import typing
import uuid

import pytest
from pydantic_core import PydanticUndefined

from src.tuiwen.model.account import Account
from src.tuiwen.model.comment import Comment, CommentCreate
from src.tuiwen.model.feedback import Feedback
from src.tuiwen.model.file import File
from src.tuiwen.model.follow import Follow, FollowCreate
from src.tuiwen.model.like import Like, LikeCreate
from src.tuiwen.model.notice import Notice
from src.tuiwen.model.post import Post, PostCreate
from src.tuiwen.model.snap import Snap
from src.tuiwen.model.video import Video, VideoSource

ALL_TABLE_MODELS = [Account, Post, Comment, Video, VideoSource, File, Follow, Like, Notice, Feedback, Snap]

# 历史遗留命名 -> 规范命名
RENAMED_COLUMNS = {
    "create_at": "created_at",
    "update_at": "updated_at",
    "nick_name": "nickname",
    "gmt_birth": "birthday",
    "obj_id": "target_id",
    "obj_type": "target_type",
}

# 不允许单独出现的含糊列名(`type` 与内置名/SQL 保留字冲突, `like` 是 SQL 运算符)
FORBIDDEN_BARE_COLUMNS = ("type", "like")


def _enum_type(annotation) -> type[enum.Enum] | None:
    """从注解里找出枚举类型(自动穿透 Optional / Union)。"""
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return annotation
    for arg in typing.get_args(annotation):
        found = _enum_type(arg)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_timestamp_columns_use_created_updated_at(model):
    """时间列只用 created_at(可再加 updated_at), 不能出现 create_at/update_at。"""
    columns = set(model.__table__.c.keys())

    assert "created_at" in columns, f"{model.__tablename__} 缺少 created_at"
    assert not {"create_at", "update_at"} & columns, f"{model.__tablename__} 仍在使用旧时间列名"


@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_no_legacy_column_names(model):
    """旧的字段命名一个都不应残留。"""
    columns = set(model.__table__.c.keys())
    leftovers = sorted(columns & set(RENAMED_COLUMNS))

    assert not leftovers, f"{model.__tablename__} 仍有旧列名: {leftovers}"


@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_no_bare_type_or_like_column(model):
    """不允许裸 `type` / `like` 列: 前者与内置名和 SQL 保留字冲突, 后者是 LIKE 运算符。"""
    columns = set(model.__table__.c.keys())
    bad = sorted(columns & set(FORBIDDEN_BARE_COLUMNS))

    assert not bad, f"{model.__tablename__} 存在含糊列名 {bad}, 请改成 notice_type/source_type/like_count 之类"


@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_enum_defaults_are_enum_members(model):
    """枚举列的默认值必须是枚举成员本身, 不能写成 .value(int)。

    写成 int 时表模型不会报错, 但序列化阶段 pydantic 会告警
    "Expected `enum` - serialized value may not be as expected", 且前端拿到的
    是裸数字而 OpenAPI 里声明的是枚举。
    """
    for name, field in model.model_fields.items():
        enum_cls = _enum_type(field.annotation)
        if enum_cls is None or field.default is PydanticUndefined or field.default is None:
            continue
        assert isinstance(field.default, enum_cls), (
            f"{model.__tablename__}.{name} 默认值应为 {enum_cls.__name__} 成员, 实际 {field.default!r}"
        )


def test_mutable_defaults_are_not_shared():
    """JSON 列的默认值必须用 default_factory, 否则所有实例共享同一个 dict/list。"""
    account_a, account_b = Account(username="a"), Account(username="b")
    account_a.extra["theme"] = "dark"

    assert account_b.extra == {}

    snap_a, snap_b = Snap(alias_name="a"), Snap(alias_name="b")
    snap_a.content["text"] = "x"

    assert snap_b.content == {}


def test_create_dtos_carry_no_identity_fields():
    """创建类请求体只收业务字段, 身份/主键/来源 IP 一律由服务端补全。"""
    assert "account_id" not in PostCreate.model_fields, "发帖入参不能带作者 ID(可冒充他人发帖)"
    assert "from_ip" not in PostCreate.model_fields, "来源 IP 由请求上下文取, 不收客户端传值"

    assert set(CommentCreate.model_fields) == {"content", "target_id", "target_type", "parent_id"}
    assert set(LikeCreate.model_fields) == {"target_id", "target_type"}
    assert set(FollowCreate.model_fields) == {"followee_id"}, "关注入参不能带 follower_id(可替他人关注)"


def test_comment_is_root_derived_from_parent_id():
    """一级/楼中楼由 parent_id 推导, 不再由客户端声明 is_root。"""
    assert "is_root" not in CommentCreate.model_fields
    assert CommentCreate(content="hi", target_id=uuid.uuid7()).parent_id is None


def test_snap_and_notice_renamed_columns_exist():
    """几处影响面最大的改名单独锁一下, 避免回退。"""
    assert "like_count" in Snap.__table__.c and "like" not in Snap.__table__.c
    assert "notice_type" in Notice.__table__.c and "type" not in Notice.__table__.c
    assert "source_type" in VideoSource.__table__.c and "type" not in VideoSource.__table__.c


def test_error_type_field_is_not_called_type():
    """转码失败回调的字段名不能叫 type。"""
    from src.tuiwen.model.video import TranscodeFailedRequest

    assert "error_type" in TranscodeFailedRequest.model_fields


@pytest.mark.parametrize("model", ALL_TABLE_MODELS, ids=lambda m: m.__tablename__)
def test_enum_columns_use_int_enum_type(model):
    """枚举列必须用 IntEnumType 映射, 而不是裸 SMALLINT。

    用裸 SMALLINT 时, asyncpg 读回来的是 int, 表模型又不做校验, 于是从库里查出的对象
    属性是 int: 序列化告警、`obj.type == XxxEnum.A` 这类比较也失去枚举语义。
    """
    from src.tuiwen.model.types import IntEnumType

    for name, field in model.model_fields.items():
        enum_cls = _enum_type(field.annotation)
        if enum_cls is None or not issubclass(enum_cls, enum.IntEnum):
            continue
        column = model.__table__.c[name]
        assert isinstance(column.type, IntEnumType), (
            f"{model.__tablename__}.{name} 是 {enum_cls.__name__} 枚举, 列类型应为 "
            f"IntEnumType({enum_cls.__name__}), 实际 {type(column.type).__name__}"
        )
        assert column.type.enum_cls is enum_cls


def test_int_enum_type_roundtrip():
    """IntEnumType 写入转 int、读出转枚举, 越界值原样透传。"""
    from src.tuiwen.model.post import PostType
    from src.tuiwen.model.types import IntEnumType

    col = IntEnumType(PostType)

    assert col.cache_ok is True, "cache_ok=False 会让 SQLAlchemy 每次都重新编译 SQL"
    assert col.process_bind_param(PostType.POST, None) == PostType.POST.value
    assert col.process_bind_param(None, None) is None
    assert col.process_result_value(PostType.POST.value, None) is PostType.POST
    assert col.process_result_value(None, None) is None
    # 库里出现枚举外的值(老数据/手改库)时不能让整条查询失败
    assert col.process_result_value(999, None) == 999
