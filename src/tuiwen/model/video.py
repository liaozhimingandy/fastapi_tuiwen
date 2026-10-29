import uuid
from enum import IntEnum, StrEnum
from typing import Optional, Dict
from datetime import datetime
from pydantic import AliasChoices, field_serializer, BaseModel

from sqlalchemy.sql.functions import func
from sqlmodel import SQLModel, Field, text
from sqlalchemy import JSON, Column, BigInteger, Identity, Boolean, UniqueConstraint, UUID

from src.tuiwen.model.types import IntEnumType, UTCDateTime
from src.tuiwen.core import get_settings
from src.tuiwen.utils.datetime_utils import to_utc, utcnow

TABLE_PREFIX = get_settings().TABLE_PREFIX


# 视频分类（短/中/长）
class VideoCategory(IntEnum):
    """视频时长分类, 由转码完成回调按 duration 归档。"""
    SHORT = 1  # <1分钟
    MEDIUM = 2  # 1-30分钟
    LONG = 3  # >30分钟


class VideoOrientation(IntEnum):
    """画面方向。转码后按 ffprobe 校正过的宽高判定, 供前端决定播放器布局。"""
    UNKNOWN = 0
    LANDSCAPE = 1  # 横屏
    PORTRAIT = 2  # 竖屏


class VideoTranscodeStatus(IntEnum):
    """转码状态机: PENDING → PROCESSING → SUCCESS / FAILED。

    回调接口据此做幂等: 已是 SUCCESS 的记录不允许被失败回调覆盖。
    """
    PENDING = 0  # 待转码
    PROCESSING = 1  # 转码中
    SUCCESS = 2  # 转码成功
    FAILED = 3  # 转码失败


class Video(SQLModel, table=True):
    """用户上传视频记录表(一条上传行为一行)。

    唯一约束 (account_id, video_md5): 同一用户重复上传同一文件只会有一条记录;
    不同用户上传相同文件则各有一条记录, 但 extra.storage_key 指向同一份底层文件(秒传)。
    """
    __tablename__ = f"{TABLE_PREFIX}video"
    __table_args__ = (UniqueConstraint("account_id", "video_md5", name="uk_tw_video_account_md5"),
                      {"comment": "用户上传视频记录表"}
                      )

    # 主键: uuid7(时间有序), 对外暴露, 替代原"自增id + video_id(uuid)"的冗余结构
    # 对外 JSON 仍沿用 video_id(兼容既有客户端)
    id: uuid.UUID = Field(
        default_factory=uuid.uuid7,
        primary_key=True,
        sa_type=UUID,
        sa_column_kwargs={"comment": "视频主键ID (uuid7)", "server_default": text("uuidv7()")},
        serialization_alias="video_id",
        validation_alias=AliasChoices("id", "video_id"),
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

    # NOTE: 三个字段都已存在对应枚举, 注解却写成 int —— 既丢掉了类型提示,
    #       OpenAPI 里也看不出取值范围。这里统一改用枚举类型。
    orientation: VideoOrientation | None = Field(
        None,
        description="视频画面方向：0未知，1横屏，2竖屏",
        sa_type=IntEnumType(VideoOrientation),
        sa_column_kwargs={"comment": "视频画面方向：0未知，1横屏，2竖屏"}
    )

    category: VideoCategory | None = Field(
        None,
        ge=0,
        description="视频时长分类：1短视频 2中视频 3长视频",
        sa_column_kwargs={"comment": "视频时长分类：1短视频 2中视频 3长视频"},
        sa_type=IntEnumType(VideoCategory)
    )

    account_id: Optional[uuid.UUID] = Field(
        None,
        description="作者账户主键",
        sa_column_kwargs={"comment": "视频作者账户主键，关联账号表"}
    )
    video_md5: Optional[str] = Field(
        None,
        max_length=32,
        description="文件MD5指纹，用于去重",
        sa_column_kwargs={"comment": "原始文件MD5，用于重复上传校验、秒传"},
        index=True  # 加索引！查询md5必须建索引
    )
    transcode_status: VideoTranscodeStatus = Field(
        default=VideoTranscodeStatus.PENDING,
        sa_column_kwargs={"comment": "转码状态：0待转码 1转码中 2成功 3失败"},
        sa_type=IntEnumType(VideoTranscodeStatus),
    )
    transcode_msg: Optional[str] = Field(None, max_length=128, sa_column_kwargs={"comment": "转码失败原因"})
    # 本次转码任务ID: 由转码服务在提交任务时回填, 回调接口用它区分「当前任务」与「过期任务」。
    # 提交转码任务的逻辑尚未实现(TODO), 因此允许为 NULL; 回调侧对 NULL 视为"首个任务直接接受"。
    # NOTE: 已有表的库需手动加列: ALTER TABLE tw_video ADD COLUMN transcode_id VARCHAR(64);
    transcode_id: Optional[str] = Field(
        None,
        max_length=64,
        index=True,
        description="本次转码任务ID",
        sa_column_kwargs={"comment": "本次转码任务ID, 转码回调幂等判断依据"},
    )

    extra: Optional[Dict] = Field(
        default_factory=dict,
        description='扩展元数据JSON',
        sa_column_kwargs={'comment': '扩展元数据JSON，存放额外信息：原始文件key、编码信息、码率等'},
        sa_type=JSON
    )

    is_deleted: bool = Field(
        False,
        description="软删除标记：false正常，true已删除",
        sa_column_kwargs={"comment": "软删除标记：false正常，true逻辑删除", "server_default": text("false")},
    )

    created_at: datetime = Field(
        ...,
        default_factory=utcnow,
        description='记录创建时间',
        sa_column=Column(
            UTCDateTime,
            default=utcnow,
            nullable=False,
            server_default=text("NOW()"),
            comment="记录创建时间（带时区）"
        )
    )

    updated_at: datetime = Field(
        ...,
        default_factory=utcnow,
        description='记录最后更新时间',
        sa_column=Column(
            UTCDateTime,
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
            comment="记录最后更新时间（带时区）"
        )
    )

    @field_serializer('created_at')
    def serialize_datetime(self, value):
        """出参时把 created_at 统一转换到配置时区(默认 Asia/Shanghai)。"""
        return to_utc(value)


# 视频源类型
class VideoSourceType(IntEnum):
    """视频源形态: HLS 为分片流(多码率自适应), MP4 为单文件直链。"""
    HLS = 1
    MP4 = 2


# 视频清晰度
class VideoQuality(StrEnum):
    """清晰度标识。

    NOTE: 取值必须与转码器实际回传/落库的档位名一致 —— 原来写的是 "360"/"720",
          而 TranscodeVariant 的文档与转码器约定是 "360p"/"720p", 两者对不上。
    """
    Q_360 = "360p"
    Q_480 = "480p"
    Q_720 = "720p"
    Q_1080 = "1080p"
    ADAPTIVE = "adaptive"  # 自适应码率


class VideoSource(SQLModel, table=True):
    """视频源表: 一条视频 × 一种类型 × 一档清晰度 = 一行。

    唯一约束 (video_id, source_type, quality) 保证回调重复写入不会产生重复源;
    url 存的是相对路径/资源标识, 对外访问地址由 Service 拼前缀生成。
    """
    __tablename__ = f"{TABLE_PREFIX}video_source"
    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "source_type",
            "quality",
            name="uq_video_source_video_type_quality",
        ),
        {'comment': '视频源表，存储视频不同码率、清晰度资源地址，一条视频可对应多条源记录'},

    )

    id: int = Field(
        None,
        primary_key=True,
        sa_column_kwargs={"comment": "表内部自增主键ID"},
        sa_type=BigInteger,
        sa_column_args=[Identity(always=False)]
    )

    video_id: uuid.UUID = Field(
        ...,
        nullable=False,
        index=True,
        description="关联视频主键ID",
        sa_column_kwargs={"comment": "关联视频主表的 id"}
    )
    url: str = Field(
        ...,
        max_length=255,
        nullable=False,
        description="视频源资源地址",
        sa_column_kwargs={"comment": "CDN资源地址，支持HLS/MP4等"}
    )

    # 字段名用 source_type: 裸 `type` 与内置名/保留字冲突, 且容易被误读成"表的类型"
    source_type: VideoSourceType = Field(
        ...,
        nullable=False,
        description="资源类型：1 HLS，2 MP4",
        sa_column_kwargs={"comment": "资源类型：1 HLS分片，2 MP4文件"},
        sa_type=IntEnumType(VideoSourceType),
        gt=0
    )

    quality: VideoQuality = Field(
        ...,
        max_length=8,
        nullable=False,
        description="清晰度标识",
        sa_column_kwargs={"comment": "清晰度标识，例如1080p、720p、480p、360p"}
    )

    # 下面三列原来写的是 `Field(..., nullable=True)` —— 「必填」与「可空」自相矛盾。
    # 实际语义是转码器可能不上报, 因此改成可选且默认 None。
    size: int | None = Field(
        None,
        description="文件大小，字节",
        sa_column_kwargs={"comment": "资源文件大小，单位：字节(byte)"}
    )

    bitrate: int | None = Field(
        None,
        description="码率，单位kbps",
        sa_column_kwargs={"comment": "视频码率，单位：kbps"}
    )

    created_at: datetime = Field(
        default_factory=utcnow,
        description='记录创建日期时间',
        sa_column=Column(
            UTCDateTime,
            default=utcnow,
            comment="记录创建日期时间（带时区）",
            nullable=False,
            server_default=text("NOW()")
        )
    )


class VideoFeedQuery(BaseModel):
    """推荐流的查询参数(cursor 优先于 feed_id: 续读时以游标内携带的 feed_id 为准)。"""
    feed_id: uuid.UUID | None = None
    cursor: str | None = None
    limit: int = Field(
        default=10,
        ge=1,
        le=20,
    )


class VideoAuthor(SQLModel):
    """视频作者信息(列表页只透出必要的展示字段)。"""
    account_id: uuid.UUID
    nickname: str | None = None
    avatar_url: str | None = None


class VideoStats(SQLModel):
    """互动统计。view/share 暂无埋点来源仍为占位; like/comment/favorite 已接真实计数。"""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    favorite_count: int = 0


class VideoInteraction(SQLModel):
    """当前登录用户对这条视频的互动状态(未登录时全为 False)。"""
    liked: bool = False
    collected: bool = False
    followed: bool = False


class VideoFeedItem(SQLModel):
    """推荐流单条视频。

    play_url 指向 master playlist(play_list.m3u8), 播放器据此自适应选码率;
    width/height/duration 用于前端在视频加载前就撑好占位区域, 避免布局抖动。
    """
    video_id: uuid.UUID
    poster_url: str | None = None
    play_url: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    orientation: VideoOrientation | None = None
    title: str | None = None
    description: str | None = None
    author: VideoAuthor | None = None
    stats: VideoStats = Field(
        default_factory=VideoStats
    )
    interaction: VideoInteraction = Field(
        default_factory=VideoInteraction
    )


class VideoFeedResponse(SQLModel):
    """推荐流响应: 本页数据 + 续读游标。

    next_cursor 为 None 时表示已到底; has_more 与它同真同假, 前端两者取其一即可。
    """
    feed_id: uuid.UUID
    items: list[VideoFeedItem]
    next_cursor: str | None = None
    has_more: bool = False


class MyVideoItem(SQLModel):
    """「我的视频」页单条(含转码状态, 便于用户知道上传后发生了什么)。

    NOTE: 不能继承 Video 表模型加字段 —— SQLModel 会把子类注册成同一张表。
    """
    video_id: uuid.UUID
    title: str | None = None
    description: str | None = None
    poster_url: str | None = None
    play_url: str | None = None
    duration: int | None = None
    orientation: VideoOrientation | None = None
    transcode_status: VideoTranscodeStatus = VideoTranscodeStatus.PENDING
    transcode_msg: str | None = None
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    created_at: datetime | None = None


class TranscodeVariant(BaseModel):
    """
    单个转码资源
    """

    quality: str = Field(
        ...,
        max_length=8,
        description="清晰度，例如360p、480p、720p、1080p",
    )
    bitrate: Optional[int] = Field(
        default=None,
        ge=0,
        description="实际视频码率，单位kbps",
    )
    size: Optional[int] = Field(
        default=None,
        ge=0,
        description="资源大小，单位byte",
    )
    url: str = Field(
        ...,
        max_length=255,
        description="资源相对路径",
    )

class TranscodeCompleteRequest(BaseModel):
    """
    视频转码完成回调
    """
    video_id: uuid.UUID = Field(
        ...,
        description="视频主键ID",
    )
    transcode_id: str = Field(
        ...,
        max_length=64,
        description="本次转码任务ID",
    )
    duration: float = Field(
        ...,
        ge=0,
        description="视频时长，单位秒",
    )
    width: int = Field(
        ...,
        gt=0,
        description="原始视频宽度",
    )
    height: int = Field(
        ...,
        gt=0,
        description="原始视频高度",
    )
    variants: list[TranscodeVariant] = Field(
        default_factory=list,
        description="转码资源",
    )


class TranscodeFailedRequest(BaseModel):
    """视频转码失败回调。

    transcode_id 用于区分"当前任务"与"过期任务": 视频可能已被重新转码,
    旧任务的失败回调不应覆盖新任务的状态。
    """
    video_id: uuid.UUID
    transcode_id: str
    # FFmpeg / 转码失败原因
    detail: str
    # 可选：错误类型，例如 ffmpeg / probe / publish / callback
    # 字段名用 error_type: `type` 与内置名/保留字冲突, 语义也太宽
    error_type: Optional[str] = None
