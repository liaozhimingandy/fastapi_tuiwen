"""评论模型: 评论表(tw_comment)与入参模型。

comment_id 采用 uuid7(时间有序), 评论分页按其做游标;
target_id + target_type 组合标识被评论的目标(帖子/其它)。
"""
from enum import IntEnum
import uuid
from datetime import datetime

from pydantic import AliasChoices, field_serializer
from sqlalchemy import DateTime, Column, BigInteger, Identity, UUID
from sqlmodel import SQLModel, Field, text

from src.tuiwen.model.types import IntEnumType
from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


class Comment(SQLModel, table=True):
    """评论数据库表(tw_comment)。

    - comment_id: uuid7 主键, 时间有序, 评论游标分页按它倒序
    - is_root/parent_id: 一级评论 is_root=True 且 parent_id 为空; 楼中楼指向父评论ID
    - target_id + target_type: 被评论的目标(帖子/其它)
    """
    __tablename__ = f"{TABLE_PREFIX}comment"  # 表名
    __table_args__ = {'comment': '评论'}  # 表备注

    class TargetTypeEnum(IntEnum):
        """评论对象类别"""
        POST = 1
        Other = 9

        @property
        def label(self):
            mapping = {
                1: "POST",
                9: "其它"
            }
            return mapping[self.value]

    # 主键即业务评论 ID: DB 列名为 id, 对外 JSON 仍沿用 comment_id(兼容既有客户端)
    id: uuid.UUID = Field(
        default_factory=uuid.uuid7,
        primary_key=True,
        sa_type=UUID,
        sa_column_kwargs={"comment": "表主键ID (uuid7)", "server_default": text("uuidv7()")},
        serialization_alias="comment_id",
        validation_alias=AliasChoices("id", "comment_id"),
    )
    is_root: bool = Field(False, description='是否为一级评论', sa_column_kwargs={'comment': '是否为一级评论'})
    parent_id: uuid.UUID | None = Field(None, description='父评论ID(楼中楼指向父评论主键)',
                                        sa_column_kwargs={'comment': '父评论ID'})
    content: str = Field(..., description='评论内容', max_length=255, sa_column_kwargs={'comment': '评论内容'})
    account_id: uuid.UUID = Field(..., index=True, description='评论者账户主键',
                                  sa_column_kwargs={'comment': '评论者账户主键'})
    target_id: uuid.UUID = Field(index=True, description='评论对象ID(帖子/其它目标的主键)',
                              sa_column_kwargs={'comment': '评论对象ID'})
    target_type: TargetTypeEnum = Field(default=TargetTypeEnum.POST, description="评论对象类别",
                                  sa_column_kwargs={'comment': '评论对象类别'},
                                  sa_type=IntEnumType(TargetTypeEnum), ge=0)
    created_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False))

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class CommentCreate(SQLModel):
    """新增评论的入参 DTO。

    NOTE: 入参不要直接用表模型 Comment:
          1) 客户端能伪造 account_id(替别人发评论) 与 is_root;
          2) SQLModel 表模型构造时不校验字段类型, 非法 UUID 会一路带到写库。
    评论者(account_id)、主键与创建时间一律由服务端补全; 一级/楼中楼由 parent_id 推导。
    """
    content: str = Field(..., max_length=255, description='评论内容')
    target_id: uuid.UUID = Field(..., description='评论对象ID(帖子等目标的主键)')
    target_type: Comment.TargetTypeEnum = Field(default=Comment.TargetTypeEnum.POST,
                                                description='评论对象类别: 1帖子 9其它')
    parent_id: uuid.UUID | None = Field(default=None, description='父评论ID; 为空表示一级评论')
