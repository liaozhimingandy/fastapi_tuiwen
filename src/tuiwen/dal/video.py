from datetime import datetime
from typing import Sequence

from sqlmodel import select, or_, and_

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.video import Video, VideoTranscodeStatus, VideoSource


class VideoDAO(BaseDAO[Video]):
    # 绑定 DAO 对应的 ORM 模型, BaseDAO 依赖该属性获取表名与字段元信息
    model = Video

    async def get_feed(
            self,
            *,
            cursor_create_at: datetime | None = None,
            cursor_id: int | None = None,
            limit: int = 10,
    ) -> list[Video]:
        statement = (
            select(Video)
            .where(
                Video.is_deleted == False,
                Video.transcode_status
                == VideoTranscodeStatus.SUCCESS,
            )
        )
        if cursor_create_at is not None:
            statement = statement.where(
                or_(
                    Video.create_at < cursor_create_at,
                    and_(
                        Video.create_at == cursor_create_at,
                        Video.id < cursor_id,
                    ),
                )
            )
        statement = (
            statement
            .order_by(
                Video.create_at.desc(),
                Video.id.desc(),
            )
            .limit(limit)
        )
        result = await self.read_db.exec(statement)
        return result.all()

    async def complete_transcode(
            self,
            video: Video,
    ) -> None:

        self.write_db.add(video)
        await self.delete_by_unique_field("video_id", video.video_id)
        await self.write_db.flush()

