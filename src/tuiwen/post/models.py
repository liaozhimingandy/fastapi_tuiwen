from enum import Enum
import uuid
from datetime import datetime, timezone

import pytz
from pydantic import field_validator

from sqlalchemy import DateTime, Enum as SaENUM, JSON
from sqlmodel import SQLModel, Field

from src.tuiwen.core import settings

TABLE_PREFIX = settings.TABLE_PREFIX

class PostRightStatusUpdate(SQLModel):
    class RightStatusEnum(Enum):
        """帖子权限"""

        PUBLIC = 1
        PRIVATE = 2

        @property
        def label(self):
            mapping = {
                1: "公开",
                2: "仅自己"
            }
            return mapping[self.value]

    post_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True, description='帖子ID',
                               sa_column_kwargs={'comment': '帖子ID'}, unique=True)
    account_id: str = Field(..., index=True, max_length=32, description='用户ID',
                            sa_column_kwargs={'comment': '用户ID'})
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, description='权限状态',
                                          sa_column_kwargs={'comment': '权限状态'},
                                          sa_type=SaENUM(RightStatusEnum,
                                                         values_callable=lambda x: [str(e.value) for e in x]))


class PostCreate(PostRightStatusUpdate):

    class FromDeviceEnum(Enum):
        """设备来源类型"""

        WEB = 1
        ANDROID = 2
        IOS = 3
        WINDOWS = 4
        UNKNOWN = 9

        @property
        def label(self):
            mapping = {
                1: "网页版",
                2: "安卓端",
                3: "IOS",
                4: "windows",
                9: "未知"
            }
            return mapping[self.value]

    content: dict | None = Field(default={}, description='json内容', max_length=1024, sa_column_kwargs={'comment': '内容'},
                         sa_type=JSON)
    from_ip: str | None = Field(None, description='来源ip',  max_length=32, sa_column_kwargs={'comment': '来源ip'})
    from_device: FromDeviceEnum = Field(FromDeviceEnum.UNKNOWN, description='来源设备名称',
                                        sa_column_kwargs={'comment': '来源设备名称'},
                                        sa_type=SaENUM(FromDeviceEnum, values_callable=lambda x: [str(e.value) for e in x]))
    location: str | None = Field(None, max_length=64, description='位置', sa_column_kwargs={'comment': '位置'})
    is_top: bool | None = Field(False, description='是否置顶', sa_column_kwargs={'comment': '是否置顶'})
    latitude: str | None = Field(None, description='经度', sa_column_kwargs={'comment': '经度'})
    longitude: str | None = Field(None, description='纬度', sa_column_kwargs={'comment': '纬度'})


class Post(PostCreate, table=True):
    """
    帖子模型
    """

    __tablename__ = f"{TABLE_PREFIX}post"  # 表名
    __table_args__ = {'comment': '帖子'}  # 表备注

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    status: int | None = Field(default=1, description='帖子状态', sa_column_kwargs={'comment': '帖子状态'})
    gmt_created: datetime = Field(..., default_factory=lambda: datetime.now(), description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))

class CommentInput(SQLModel):
    """
        评论模型
        """

    class ObjTypeEnum(Enum):
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

    __tablename__ = f"{TABLE_PREFIX}comment"  # 表名
    __table_args__ = {'comment': '评论'}  # 表备注

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    comment_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True, description='评论ID',
                                  sa_column_kwargs={'comment': '评论ID'}, unique=True)
    is_root: bool = Field(False, description='是否为一级评论', sa_column_kwargs={'comment': '是否为一级评论'})
    parent_id: str | None = Field(None, description='父评论', max_length=32, sa_column_kwargs={'comment': '父评论'})
    content: str = Field(..., description='评论内容', max_length=255, sa_column_kwargs={'comment': '评论内容'})
    account_id: str = Field(..., index=True, max_length=32, description='评论者',
                            sa_column_kwargs={'comment': '评论者'})
    obj_id: str = Field(index=True, description='评论对象ID', max_length=36,
                        sa_column_kwargs={'comment': '评论对象ID'})
    obj_type: ObjTypeEnum = Field(default=ObjTypeEnum.POST, description="评论对象类别",
                                  sa_column_kwargs={'comment': '评论对象类别'},
                                  sa_type=SaENUM(ObjTypeEnum, values_callable=lambda x: [str(e.value) for e in x]))
    gmt_created: datetime = Field(..., default_factory=lambda: datetime.now(), description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))

    @field_validator('gmt_created', mode="after")  # type: ignore[prop-decorator]
    @classmethod
    def convert_to_cst(cls, value):
        if value is None:
            return None

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(pytz.timezone(settings.TIME_ZONE))

class Comment(CommentInput, table=True):
    pass


class LikeInput(SQLModel):
    """
        赞模型
        """

    __tablename__ = f"{TABLE_PREFIX}like"  # 表名
    __table_args__ = {'comment': '赞'}  # 表备注

    class ObjTypeEnum(Enum):
        """评论对象类别"""
        POST = 1

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    obj_id: uuid.UUID = Field(index=True, description='赞对象ID', sa_column_kwargs={'comment': '赞对象ID'})
    obj_type: ObjTypeEnum = Field(default=ObjTypeEnum.POST, description="评论对象类别",
                                  sa_column_kwargs={'comment': '评论对象类别'},
                                  sa_type=SaENUM(ObjTypeEnum, values_callable=lambda x: [str(e.value) for e in x]))
    account_id: str = Field(..., index=True, max_length=32, description='点赞的用户',
                            sa_column_kwargs={'comment': '点赞的用户'})
    gmt_created: datetime = Field(default_factory=lambda: datetime.now(), description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))

class Like(LikeInput, table=True):
    pass

class ImageBase(SQLModel):
    image_url: str = Field(..., max_length=128, description='图片url', sa_column_kwargs={'comment': '图片url'})
    image_md5: str = Field(..., max_length=32, min_length=32, index=True, description='图片md值',
                           sa_column_kwargs={'comment': '图片md值'}, unique=True)


class Image(ImageBase, table=True):
    """
    上传文件图片模型
    """

    __tablename__ = f"{TABLE_PREFIX}image"  # 表名
    __table_args__ = {'comment': '图片'}  # 表备注

    id: int = Field(primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    image_name: str = Field(..., max_length=128, description='图片名称', sa_column_kwargs={'comment': '图片名称'})
    gmt_created: datetime = Field(default_factory=lambda: datetime.now(), description='创建时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))