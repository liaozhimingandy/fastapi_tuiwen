"""上传文件模型: 通用文件表(tw_file), 图片/视频/音频/文档统一存储。

以内容 MD5 作为唯一键实现秒传(同文件重复上传直接复用已有记录),
差异化元数据(宽高/时长/封面)统一放 extra JSONB。
"""
from typing import Optional
from datetime import datetime
from pydantic import field_serializer
from sqlalchemy import DateTime, JSON, Column, BigInteger, SMALLINT, Identity
from sqlmodel import SQLModel, Field, text

from src.tuiwen.core import get_settings
from src.tuiwen.utils.utils import convert_to_timezone

TABLE_PREFIX = get_settings().TABLE_PREFIX

class File(SQLModel, table=True):
    """通用文件数据库表(tw_file), 图片/视频/音频/文档统一存储。

    - file_md5: 内容摘要(唯一索引) → 秒传判定, 同文件重复上传直接复用记录
    - storage_key: 对象存储里的真实 key, url 只是访问地址
    - status: 0临时(已上传未绑定业务) / 1正常 / 2已标记删除
    - extra: JSONB, 存宽高/时长/封面key等差异化元数据
    """

    __tablename__ = f"{TABLE_PREFIX}file"  # 表名
    __table_args__ = {'comment': '图片'}  # 表备注

    id: int = Field(None, primary_key=True, sa_column_kwargs={"comment": "表主键ID", }, sa_type=BigInteger,
                    sa_column_args=[Identity(always=False)])
    file_type: int = Field(default=1, max_length=16, description="文件类型:image/video/audio/doc", ge=0, sa_type=SMALLINT,)
    url: str = Field(..., max_length=128, description='文件url', sa_column_kwargs={'comment': '文件url'})
    storage_key: str = Field(..., max_length=64, description="对象存储key", index=True)
    original_name: Optional[str] = Field(None, max_length=128, description="用户原始文件名")
    mime_type: str = Field(..., max_length=64, description="mime类型 image/png video/mp4")
    file_md5: str = Field(..., max_length=32, min_length=32, index=True, description='文件md值',
                           sa_column_kwargs={'comment': '文件md值'}, unique=True)
    file_size: int = Field(..., description="文件字节大小")
    account_id: str = Field(..., max_length=64, index=True, description="上传账号ID")
    # 图片宽高、视频时长、封面等差异化字段全部放jsonb
    extra: Optional[dict] = Field(default={}, description='json内容', max_length=1024,
                                 sa_column_kwargs={'comment': '扩展元数据：宽高、时长、封面key等'},
                                 sa_type=JSON)
    status: int = Field(default=1, description="0临时 1正常可用 2已标记删除", ge=0, sa_type=SMALLINT,
                        sa_column_kwargs={'comment': '0临时 1正常可用 2已标记删除'})
    create_at: datetime = Field(..., default_factory=datetime.now, description='创建日期时间',
                                sa_column=Column(DateTime(timezone=True), default=datetime.now,
                                                 comment="创建日期时间", nullable=False,
                                                 server_default=text("NOW()")))

    @field_serializer('create_at')
    def serialize_datetime(self, value):
        return convert_to_timezone(value)







