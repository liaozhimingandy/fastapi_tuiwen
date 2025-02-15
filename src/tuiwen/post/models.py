from enum import Enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SaENUM, JSON
from sqlmodel import SQLModel, Field

from src.tuiwen.config import settings

TABLE_PREFIX = settings.TABLE_PREFIX


class PostCreate(SQLModel):
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

    post_id: uuid.UUID = Field(default_factory=uuid.uuid4, index=True, description='帖子ID',
                          sa_column_kwargs={'comment': '帖子ID'}, unique=True)
    content: dict | None = Field(default={}, description='json内容', max_length=1024, sa_column_kwargs={'comment': '内容'},
                         sa_type=JSON)
    account_id: str = Field(..., index=True, max_length=32, description='用户ID', sa_column_kwargs={'comment': '用户ID'})
    from_ip: str | None = Field(None, description='来源ip',  max_length=32, sa_column_kwargs={'comment': '来源ip'})
    from_device: FromDeviceEnum = Field(FromDeviceEnum.UNKNOWN, description='来源设备名称',
                                        sa_column_kwargs={'comment': '来源设备名称'},
                                        sa_type=SaENUM(FromDeviceEnum, values_callable=lambda x: [str(e.value) for e in x]))
    right_status: RightStatusEnum = Field(default=RightStatusEnum.PUBLIC, description='权限状态',
                                          sa_column_kwargs={'comment': '权限状态'},
                                          sa_type=SaENUM(RightStatusEnum, values_callable=lambda x: [str(e.value) for e in x]))
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
    gmt_created: datetime = Field(default_factory=datetime.now, description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))


class Comment(SQLModel, table=True):
    """
    评论模型
    """

    __tablename__ = f"{TABLE_PREFIX}comment"  # 表名
    __table_args__ = {'comment': '评论'}  # 表备注

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    comment_id: uuid.UUID = Field(default_factory=uuid.uuid4,  index=True, description='评论ID',
                             sa_column_kwargs={'comment': '评论ID'}, unique=True)
    is_root: bool = Field(False, description='是否为一级评论', sa_column_kwargs={'comment': '是否为一级评论'})
    parent_id: str | None = Field(None, description='父评论', max_length=32, sa_column_kwargs={'comment': '父评论'})
    content: str = Field(..., description='评论内容', max_length=255, sa_column_kwargs={'comment': '评论内容'})
    account_id: str = Field(..., index=True, max_length=32, description='评论者', sa_column_kwargs={'comment': '评论者'})
    post_id: uuid.UUID = Field(index=True, description='评论对象ID',  max_length=32, sa_column_kwargs={'comment': '评论对象ID'})
    gmt_created: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))


class Like(SQLModel, table=True):
    """
    赞模型
    """

    __tablename__ = f"{TABLE_PREFIX}like"  # 表名
    __table_args__ = {'comment': '赞'}  # 表备注

    id: int = Field(None, primary_key=True, description='表主键ID', sa_column_kwargs={'comment': '表主键ID'})
    post_id: uuid.UUID = Field(index=True, description='赞对象ID', sa_column_kwargs={'comment': '赞对象ID'})
    account_id: str = Field(...,  index=True, max_length=32, description='点赞的用户', sa_column_kwargs={'comment': '点赞的用户'})
    gmt_created: datetime = Field(default_factory=datetime.now, description='创建日期时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))

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
    gmt_created: datetime = Field(default_factory=datetime.now, description='创建时间',
                                  sa_column_kwargs={'comment': '创建日期时间'},
                                  sa_type=DateTime(timezone=True))