"""模型层共用的自定义列类型。

背景: 枚举列在库里是 SMALLINT, asyncpg 读回来是纯 int。SQLModel 表模型不做校验,
      所以从数据库查出的对象属性是 int 而不是枚举成员 —— 序列化时 pydantic 会刷
      `PydanticSerializationUnexpectedValue(Expected 'enum' ...)`, 虽然 JSON 值是对的,
      但日志噪音很大, 也让 `post.post_type == PostType.BLOG` 这类比较依赖 IntEnum 的
      int 语义(换成 StrEnum 就会静默失效)。

IntEnumType 在「写入」时把枚举转成 int, 「读取」时再转回枚举成员,
是这一层唯一需要关心的转换点。

UTCDateTime 同理是时间列的**唯一**转换点: 读写两侧都归一成 tz-aware UTC,
让「naive 时间按谁解释」这个歧义不在业务代码里出现。
"""
from datetime import datetime
from enum import IntEnum

from sqlalchemy import SMALLINT, DateTime
from sqlalchemy.types import TypeDecorator

from src.tuiwen.utils.datetime_utils import to_utc


class IntEnumType(TypeDecorator):
    """把 SMALLINT 列映射成指定的 IntEnum, 读写两侧自动转换。

    用法::

        post_type: PostType = Field(PostType.POST, sa_type=IntEnumType(PostType))

    NOTE: 必须设置 cache_ok = True, 否则 SQLAlchemy 会把它当成不可缓存的类型,
          每次执行都要重新编译 SQL 结构, 性能与日志都很吵。
    """
    impl = SMALLINT
    cache_ok = True

    def __init__(self, enum_cls: type[IntEnum], *args, **kwargs):
        self.enum_cls = enum_cls
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        """写入: 枚举成员/整数 -> int; None 原样透传。"""
        if value is None:
            return None
        return int(value)

    def process_result_value(self, value, dialect):
        """读取: int -> 枚举成员; 库里的值不在枚举范围内时保持原值, 不让整条查询失败。"""
        if value is None:
            return None
        try:
            return self.enum_cls(value)
        except ValueError:
            return value

    def copy(self, **kw):
        return IntEnumType(self.enum_cls, **kw)


class UTCDateTime(TypeDecorator):
    """timestamptz 列, 读写两侧都归一成 tz-aware UTC。

    用法::

        created_at: datetime = Field(..., sa_column=Column(UTCDateTime, default=utcnow, ...))

    为什么必须在类型层做, 而不是靠"调用方小心":
        asyncpg 对 timestamptz 的 naive 参数按**进程本地时区**解释。也就是说同一个
        ``datetime.now()`` 值, 开发机(TZ=Asia/Shanghai)与容器(TZ=UTC)写进去是两个
        相差 8 小时的时刻, 而代码和日志里完全看不出来。在类型层把 naive 一律按 UTC
        处理, 上层就不必再关心这件事。

    NOTE: impl 仍是 DateTime(timezone=True), 建表语句与既有库结构完全一致, 不需要迁移。
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """写入: naive 按 UTC 补齐, aware 统一换算成 UTC; None 原样透传。"""
        return to_utc(value) if isinstance(value, datetime) else value

    def process_result_value(self, value, dialect):
        """读取: 补回 UTC tzinfo, 保证业务层拿到的一定是 aware 值。"""
        return to_utc(value) if isinstance(value, datetime) else value

    def copy(self, **kw):
        return UTCDateTime(**kw)
