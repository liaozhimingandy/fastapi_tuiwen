"""评论模型: 评论表(tw_comment)与入参模型。

comment_id 采用 uuid7(时间有序), 评论分页按其做游标;
obj_id + obj_type 组合标识被评论的目标(帖子/其它)。
"""
from enum import IntEnum
import uuid
from uuid import UUID
from datetime import datetime

from pydantic import field_serializer
from sqlalchemy import DateTime, Column, BigInteger, SMALLINT, Identity
from sqlmodel import SQLModel, Field, text

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX


class CommentInput(SQLModel):
    """
    评论模型
    """

    class ObjTypeEnum(IntEnum):
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

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    comment_id: UUID = Field(default_factory=uuid.uuid7, index=True, description='评论ID',
                             sa_column_kwargs={'comment': '评论ID', "server_default": text("uuidv7()")},
                             unique=True)
    is_root: bool = Field(False, description='是否为一级评论', sa_column_kwargs={'comment': '是否为一级评论'})
    parent_id: str | None = Field(None, description='父评论', max_length=32, sa_column_kwargs={'comment': '父评论'})
    content: str = Field(..., description='评论内容', max_length=255, sa_column_kwargs={'comment': '评论内容'})
    account_id: str = Field(..., index=True, max_length=32, description='评论者',
                            sa_column_kwargs={'comment': '评论者'})
    obj_id: str = Field(index=True, description='评论对象ID', max_length=36,
                        sa_column_kwargs={'comment': '评论对象ID'})
    obj_type: ObjTypeEnum = Field(default=ObjTypeEnum.POST, description="评论对象类别",
                                  sa_column_kwargs={'comment': '评论对象类别'},
                                  sa_type=SMALLINT, ge=0)
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                   comment="创建日期时间", nullable=False))

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


class Comment(CommentInput, table=True):
    """评论数据库表(tw_comment)。"""
    __tablename__ = f"{TABLE_PREFIX}comment"  # 表名
    __table_args__ = {'comment': '评论'}  # 表备注