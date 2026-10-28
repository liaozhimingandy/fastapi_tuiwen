"""视频表 DAO。

除通用 CRUD 外, 只放两类专属查询:
    get_feed            —— 推荐流游标分页(按 created_at + id 双键倒序, 避免同一时间戳翻页丢数据)
    complete_transcode  —— 转码完成后的落库(见方法内 NOTE)
"""
import uuid
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
            cursor_id: uuid.UUID | None = None,
            limit: int = 10,
    ) -> list[Video]:
        """推荐流查询: 只取已转码成功且未删除的视频, 按时间倒序。

        游标分页用 (created_at, id) 双键而非单纯 offset:
            条件为 created_at < cursor_time OR (created_at == cursor_time AND id < cursor_id)
        这样同一 created_at 上的多条记录不会在翻页时被跳过或重复。

        Args:
            cursor_create_at: 上一页最后一条的 created_at; None 表示第一页
            cursor_id: 上一页最后一条的主键 id(uuid7); 与 cursor_create_at 配对使用
            limit: 返回条数(调用方通常传 limit+1 用于判断 has_more)

        Returns:
            list[Video]: 按 created_at desc, id desc 排序的视频列表
        """
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
                    Video.created_at < cursor_create_at,
                    and_(
                        Video.created_at == cursor_create_at,
                        Video.id < cursor_id,
                    ),
                )
            )
        statement = (
            statement
            .order_by(
                Video.created_at.desc(),
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
        """转码完成后把已改好状态的实体合并进写会话并 flush(不 commit, 事务出口在上层)。

        Args:
            video: 已改好 transcode_status / width / height / duration / orientation 的实体

        注意: 旧实现在这里按 video_id 执行了 delete_by_unique_field, 会把刚更新的
              视频行删掉; 现已移除。旧 video_source 行的清理由 Service 在
              VideoSourceDAO 上做(delete_by_fields), 与本方法无关。
        """
        self.write_db.add(video)
        await self.write_db.flush()
