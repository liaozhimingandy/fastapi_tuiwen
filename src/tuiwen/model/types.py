"""模型层共用的自定义列类型。

背景: 枚举列在库里是 SMALLINT, asyncpg 读回来是纯 int。SQLModel 表模型不做校验,
      所以从数据库查出的对象属性是 int 而不是枚举成员 —— 序列化时 pydantic 会刷
      `PydanticSerializationUnexpectedValue(Expected 'enum' ...)`, 虽然 JSON 值是对的,
      但日志噪音很大, 也让 `post.post_type == PostType.BLOG` 这类比较依赖 IntEnum 的
      int 语义(换成 StrEnum 就会静默失效)。

IntEnumType 在「写入」时把枚举转成 int, 「读取」时再转回枚举成员,
是这一层唯一需要关心的转换点。
"""
from enum import IntEnum

from sqlalchemy import SMALLINT
from sqlalchemy.types import TypeDecorator


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
