import uuid
from enum import IntEnum, StrEnum
from typing import Optional, Dict
from datetime import datetime
from pydantic import field_serializer

from sqlalchemy.sql.functions import func
from sqlmodel import SQLModel, Field, text
from sqlalchemy import DateTime, JSON, Column, BigInteger, SMALLINT, Identity, Boolean, UniqueConstraint

from src.tuiwen.common.snowflake import gen_snowflake_id
from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

# 视频分类（短/中/长）
class VideoCategory(IntEnum):
    SHORT = 1   # <1分钟
    MEDIUM = 2  # 1-30分钟
    LONG = 3      # >30分钟


class VideoOrientation(IntEnum):
    UNKNOWN = 0
    LANDSCAPE = 1  # 横屏
    PORTRAIT = 2   # 竖屏


class VideoTranscodeStatus(IntEnum):
    PENDING = 0   # 待转码
    PROCESSING = 1  # 转码中
    SUCCESS = 2   # 转码成功
    FAILED = 3    # 转码失败


class Video(SQLModel, table=True):
    __tablename__ = f"{TABLE_PREFIX}video"
    __table_args__ = (UniqueConstraint("account_id", "video_md5", name="uk_tw_video_account_md5"),
                      {"comment": "用户上传视频记录表"}
                      )

    # 内部自增主键，仅数据库内部使用，业务对外不暴露
    id: int = Field(
        None,
        primary_key=True,
        sa_column_kwargs={"comment": "数据库内部自增主键ID"},
        sa_type=BigInteger,
        sa_column_args=[Identity(always=False)]
    )

    # 业务对外视频ID：雪花64位Bigint，唯一索引
    video_id: uuid.UUID = Field(
        default_factory=uuid.uuid7,
        index=True,
        unique=True,
        description='业务视频雪花ID（对外暴露）',
        sa_column_kwargs={'comment': '业务视频ID，对外接口使用，全局唯一', "server_default": text("uuidv7()")},
        max_length=36
    )

    poster: Optional[str] = Field(
        None,
        max_length=255,
        description="视频封面CDN地址",
        sa_column_kwargs={"comment": "视频封面CDN地址"}
    )

    width: int | None = Field(
        None,
        gt=0,
        description="视频宽度，像素",
        sa_column_kwargs={"comment": "视频分辨率宽度（px）"}
    )

    height: int | None = Field(
        None,
        gt=0,
        description="视频高度，像素",
        sa_column_kwargs={"comment": "视频分辨率高度（px）"}
    )

    duration: Optional[int] = Field(
        None,
        ge=0,
        description="视频时长，单位秒",
        sa_column_kwargs={"comment": "视频播放时长（秒）"}
    )

    title: Optional[str] = Field(
        None,
        max_length=200,
        description="视频标题",
        sa_column_kwargs={"comment": "视频标题"}
    )

    description: Optional[str] = Field(
        None,
        description="视频简介描述",
        sa_column_kwargs={"comment": "视频简介描述文本"}
    )

    orientation: Optional[int] = Field(
        None,
        description="视频画面方向：0未知，1横屏，2竖屏",
        sa_column_kwargs={"comment": "视频画面方向：0未知，1横屏，2竖屏"}
    )

    category: Optional[int] = Field(
        None,
        ge=0,
        description="视频长短分类 0短视频，1长视频",
        sa_column_kwargs={"comment": "视频长短分类：0短视频，1长视频"},
        sa_type=SMALLINT
    )

    default_url: str = Field(
        ...,
        max_length=255,
        description="默认播放地址（HLS/MP4）",
        sa_column_kwargs={"comment": "默认播放资源地址，优先播放此地址"}
    )

    account_id: Optional[str] = Field(
        None,
        max_length=8,
        description="作者账号雪花ID",
        sa_column_kwargs={"comment": "视频作者账号雪花ID，关联账号表"}
    )
    video_md5: Optional[str] = Field(
        None,
        max_length=32,
        description="文件MD5指纹，用于去重",
        sa_column_kwargs={"comment": "原始文件MD5，用于重复上传校验、秒传"},
        index=True  # 加索引！查询md5必须建索引
    )
    transcode_status: int = Field(
        default=VideoTranscodeStatus.PENDING,
        sa_column_kwargs={"comment": "转码状态：0待转码 1转码中 2成功 3失败"},
        sa_type=SMALLINT,
    )
    transcode_msg: Optional[str] = Field(None, max_length=128, sa_column_kwargs={"comment": "转码失败原因"})

    extra: Optional[Dict] = Field(
        default={},
        description='扩展元数据JSON',
        sa_column_kwargs={'comment': '扩展元数据JSON，存放额外信息：原始文件key、编码信息、码率等'},
        sa_type=JSON
    )

    is_deleted: bool = Field(
        False,
        description="软删除标记：false正常，true已删除",
        sa_column_kwargs={"comment": "软删除标记：false正常，true逻辑删除",  "server_default": text("false")},
    )

    create_at: datetime = Field(
        ...,
        default_factory=datetime.now,
        description='记录创建时间',
        sa_column=Column(
            DateTime(timezone=True),
            default=datetime.now,
            nullable=False,
            server_default=text("NOW()"),
            comment="记录创建时间（带时区）"
        )
    )

    update_at: datetime = Field(
        ...,
        default_factory=datetime.now,
        description='记录最后更新时间',
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
            comment="记录最后更新时间（带时区）"
        )
    )

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)


# 视频源类型
class VideoSourceType(StrEnum):
    MP4 = "video/mp4" # 1
    HLS = "application/x-mpegURL" # 2

# 视频清晰度
class VideoQuality(StrEnum):
    Q_360 = "360"
    Q_720 = "720"
    Q_1080 = "1080"
    ADAPTIVE = "adaptive"  # 自适应码率


class VideoSource(SQLModel, table=True):
    __tablename__ = f"{TABLE_PREFIX}video_source"
    __table_args__ = {'comment': '视频源表，存储视频不同码率、清晰度资源地址，一条视频可对应多条源记录'}

    id: int = Field(
        None,
        primary_key=True,
        sa_column_kwargs={"comment": "表内部自增主键ID"},
        sa_type=BigInteger,
        sa_column_args=[Identity(always=False)]
    )

    video_id: str = Field(
        ...,
        nullable=False,
        index=True,
        description="关联视频ID",
        sa_column_kwargs={"comment": "关联视频主表的业务雪花video_id"},
        max_length=36
    )

    url: str = Field(
        ...,
        max_length=128,
        nullable=False,
        description="视频源资源地址",
        sa_column_kwargs={"comment": "CDN资源地址，支持HLS/MP4等"}
    )

    type: int = Field(
        ...,
        nullable=True,
        description="资源类型：1 HLS，2 MP4",
        sa_column_kwargs={"comment": "资源类型：1 HLS分片，2 MP4文件"},
        sa_type=SMALLINT,
        gt=0
    )

    quality: str = Field(
        ...,
        max_length=8,
        nullable=True,
        description="清晰度标识",
        sa_column_kwargs={"comment": "清晰度标识，例如1080p、720p、480p、360p"}
    )

    size: int = Field(
        ...,
        nullable=True,
        description="文件大小，字节",
        sa_column_kwargs={"comment": "资源文件大小，单位：字节(byte)"}
    )

    bitrate: int = Field(
        ...,
        nullable=True,
        description="码率，单位kbps",
        sa_column_kwargs={"comment": "视频码率，单位：kbps"}
    )

    create_at: datetime = Field(
        default_factory=datetime.now,
        description='记录创建日期时间',
        sa_column=Column(
            DateTime(timezone=True),
            default=datetime.now,
            comment="记录创建日期时间（带时区）",
            nullable=False,
            server_default=text("NOW()")
        )
    )


