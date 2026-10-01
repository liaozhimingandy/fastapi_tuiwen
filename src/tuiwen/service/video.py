import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.tuiwen import get_settings
from src.tuiwen.common.feed_cursor import FeedCursor
from src.tuiwen.core.storage import Storage
from src.tuiwen.core.storage import storage
from src.tuiwen.dal.video_source import VideoSourceDAO
from src.tuiwen.model.video import Video, VideoOrientation, VideoTranscodeStatus, VideoFeedResponse, VideoInteraction, \
    VideoStats, VideoFeedItem, VideoSource, VideoSourceType, TranscodeFailedRequest
from src.tuiwen.dal.video import VideoDAO
from src.tuiwen.common.exceptions import BizError
from src.tuiwen.utils import logger


@dataclass
class VideoService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。
    """

    dao: VideoDAO
    source_dao: VideoSourceDAO
    chunk_size: int = 1024 * 1024  # 1MB 分片，可调整
    storage: Storage = storage

    @staticmethod
    def _calc_orientation(width: int, height: int) -> int:
        if width <= 0 or height <= 0:
            return VideoOrientation.UNKNOWN
        return VideoOrientation.LANDSCAPE if width > height else VideoOrientation.PORTRAIT

    @staticmethod
    def _build_play_url(video: Video) -> str:
        ym = video.create_at.strftime("%Y%m")
        return (
            f"{get_settings().VIDEO_STORAGE_URL_PREFIX}"
            f"{ym}/"
            f"{video.video_id}/"
            f"hls/playlist.m3u8"
        )

    @staticmethod
    def _build_poster_url(video: Video) -> str:
        ym = video.create_at.strftime("%Y%m")
        return (
            f"{get_settings().VIDEO_STORAGE_URL_PREFIX}"
            f"{ym}/"
            f"{video.video_id}/"
            f"poster.jpg"
        )

    async def upload(
            self,
            upload_file,
            max_size: int,
            title: str | None,
            description: str | None,
            category: int | None,
            uploader_account_id: str = "1",
            video_md5: Optional[str] = None,
    ) -> Video:
        """
        流式上传视频。
        处理逻辑：
        1. 前端 MD5 仅用于预检查，不直接信任。
        2. 服务端重新计算真实 MD5。
        3. 根据真实 MD5 查找已有视频资源。
        4. 如果底层文件已经存在：
            - 不重复上传文件
            - 不重复转码
            - 新建当前用户自己的 Video 记录
            - 复用已有 storage_key
        5. 如果底层文件不存在：
            - 上传原始文件
            - 新建 Video
            - 后续进入转码流程
        """
        settings = get_settings()
        video_id = uuid.uuid7()
        filename = upload_file.filename or ""
        ext = Path(filename).suffix.lower() or ".mp4"

        # ---------------------------------------------------------
        # 1. 前端 MD5 预检查
        # ---------------------------------------------------------
        # 注意：
        # 前端传来的 MD5 不能作为最终依据。
        # 它只能用于提前告诉服务端：
        # “我认为这个文件是 xxx”
        # 真正入库时必须使用服务端计算出的 MD5。
        if video_md5:
            existing_video = await self.dao.get_one(
                video_md5=video_md5,
                account_id=uploader_account_id,
            )
            if existing_video:
                return existing_video

        # ---------------------------------------------------------
        # 2. 创建临时文件
        # ---------------------------------------------------------
        temp_dir = Path(
            settings.VIDEO_STORAGE_DIR,
            "tmp",
        )
        temp_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        temp_file_path = temp_dir / f"{video_id}{ext}"
        md5_obj = hashlib.md5()
        total_bytes = 0

        try:
            # -----------------------------------------------------
            # 3. 流式读取 UploadFile
            # -----------------------------------------------------
            with temp_file_path.open("wb") as temp_file:
                while True:
                    chunk = await upload_file.read(self.chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)

                    # 超过大小限制
                    if total_bytes > max_size:
                        raise BizError(
                            code=413,
                            message=(
                                f"文件不能超过 "
                                f"{max_size / 1024 / 1024:.2f}MB"
                            ),
                        )
                    # 计算服务端真实 MD5
                    md5_obj.update(chunk)
                    # 写入临时文件
                    temp_file.write(chunk)

            # -----------------------------------------------------
            # 4. 空文件检查
            # -----------------------------------------------------
            if total_bytes == 0:
                raise BizError(
                    code=400,
                    message="文件为空",
                )

            # -----------------------------------------------------
            # 5. 获取服务端真实 MD5
            # -----------------------------------------------------
            file_md5 = md5_obj.hexdigest()

            # -----------------------------------------------------
            # 6. 二次查重
            # -----------------------------------------------------
            # 这里必须使用真实 MD5。
            # 注意：
            # 这里不要再限定 account_id。
            # 因为你的目标是：
            # 不同用户上传相同文件
            # ↓
            # 底层文件只保存一次
            existing_video = await self.dao.get_one(
                video_md5=file_md5
            )

            # -----------------------------------------------------
            # 7. 确定底层存储资源
            # -----------------------------------------------------
            storage_key: str
            need_transcode: bool

            if existing_video:
                # =================================================
                # 已经存在底层文件
                # =================================================
                existing_storage_key = (existing_video.extra or {}).get("storage_key")
                if not existing_storage_key:
                    raise BizError(
                        code=500,
                        message="已有视频记录缺少存储地址",
                    )
                storage_key = existing_storage_key
                # 不需要再次上传
                # 不需要再次转码
                need_transcode = False
                # 临时文件可以删除
                temp_file_path.unlink(missing_ok=True)
            else:
                # =================================================
                # 第一次上传这个文件
                # =================================================
                # 注意：
                # storage.save() 应该接收“临时文件路径”，
                # 而不是再次使用已经读取完毕的 UploadFile。
                # 这里假设你的 StorageService 支持：
                # save_file(video_id, file_path, ext)
                upload_file.file.seek(0)
                storage_key = await self.storage.save(
                    str(video_id),
                    upload_file,
                    ext,
                )
                need_transcode = True

            # -----------------------------------------------------
            # 8. 创建当前用户自己的 Video 记录
            # -----------------------------------------------------
            video = Video(
                video_id=video_id,
                poster=None,
                title=title,
                description=description,
                category=category,
                account_id=uploader_account_id,
                video_md5=file_md5,
                transcode_status=(
                    VideoTranscodeStatus.PENDING if need_transcode else VideoTranscodeStatus.SUCCESS
                ),
                transcode_msg=None,
                is_deleted=False,
                extra={
                    # 原始文件名
                    "original_filename": filename,
                    # 真正的存储 Key
                    # 注意：
                    # 这里保存 storage_key，
                    # 不保存 CDN URL。
                    "storage_key": storage_key,
                    # 文件大小
                    "size_bytes": total_bytes,
                    # MIME 类型
                    "content_type": upload_file.content_type,
                    # 文件后缀
                    "file_suffix": ext,
                    # 上传时间
                    "upload_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            # -----------------------------------------------------
            # 9. 写入数据库
            # -----------------------------------------------------
            instance = await self.dao.create(video)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)

            # -----------------------------------------------------
            # 10. 删除临时文件
            # -----------------------------------------------------
            temp_file_path.unlink(missing_ok=True)

            # -----------------------------------------------------
            # 11. 投递转码任务
            # -----------------------------------------------------
            # 只有真正第一次出现的文件才需要转码。
            if need_transcode:
                # TODO:
                # await self.transcode_service.submit(
                #     video_id=video_id,
                #     storage_key=storage_key,
                # )
                pass

            return instance

        except Exception:
            # 发生异常时清理临时文件
            temp_file_path.unlink(missing_ok=True)
            raise
        finally:
            # 关闭 UploadFile
            await upload_file.close()

    async def feed(self, feed_id: Optional[str] = None, limit: int = 10,
                   cursor: Optional[str] = None) -> VideoFeedResponse:
        """
        {
            "feed_id": "0199c8a2-7d35-7abc-8def-123456789abc",
            "items": [],
            "next_cursor": "eyJ...",
            "has_more": true
            }
        :param feed_id:
        :param limit:
        :param cursor:
        :return:
        """

        # 第一次请求
        if cursor:
            try:
                decoded = FeedCursor.decode(cursor)
            except ValueError:
                raise BizError(
                    code=400,
                    message="无效的分页游标",
                )

            # cursor 中的 feed_id 优先
            feed_id = decoded.feed_id
            videos = await self.dao.get_feed(
                cursor_create_at=decoded.create_at,
                cursor_id=decoded.id,
                limit=limit + 1,
            )
        else:
            # 新建一次 Feed Session
            feed_id = feed_id or uuid.uuid7()
            videos = await self.dao.get_feed(
                limit=limit + 1,
            )
        # 多查询一条，用于判断 has_more
        has_more = len(videos) > limit
        if has_more:
            videos = videos[:limit]
        items = []
        for video in videos:
            item = VideoFeedItem(
                video_id=video.video_id,
                poster_url=self._build_poster_url(video),
                play_url=self._build_play_url(video),
                width=video.width,
                height=video.height,
                duration=video.duration,
                orientation=video.orientation,
                title=video.title,
                description=video.description,
                stats=VideoStats(),
                interaction=VideoInteraction(),
            )
            items.append(item)

        # 生成下一页 Cursor
        next_cursor = None
        if has_more and videos:
            last_video = videos[-1]

            next_cursor = FeedCursor.encode(
                feed_id=feed_id,
                create_at=last_video.create_at,
                id=last_video.id,
            )

        return VideoFeedResponse(
            feed_id=feed_id,
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def transcode_complete(self, data):
        video = await self.dao.get_by_unique_field("video_id", data["video_id"])

        if video is None:
            raise BizError(
                f"视频不存在: {data.video_id}"
            )

        # 已经成功，重复回调直接幂等返回
        if video.transcode_status == VideoStats.READY:
            return True

        # 不是当前转码任务
        if video.transcode_id != data.transcode_id:
            logger.warning(
                "忽略旧转码任务回调: video_id=%s",
                data.video_id,
            )
            return False

        if not data.variants:
            raise BizError(
                "转码结果为空"
            )

        sources = [
            VideoSource(
                video_id=video.video_id,
                type=VideoSourceType.HLS,
                quality=item.quality,
                path=item.path,
                size=item.size,
                bitrate=item.bitrate,
            )
            for item in data.variants
        ]

        video.transcode_status = VideoStats.READY
        video.duration = data.duration
        video.width = data.width
        video.height = data.height
        video.transcode_msg = None

        await self.dao.complete_transcode(video=video)
        await self.source_dao.bulk_create(sources)
        await self.source_dao.commit()
        await self.dao.write_db.commit()

        return True

    async def transcode_failed(self, data: TranscodeFailedRequest,) -> bool:
        video = self.dao.get_by_unique_field("video_id", data.video_id)

        if video is None:
            raise BizError(f"视频不存在: {data.video_id}")

        # 已经成功，不允许失败回调覆盖 READY
        if video.transcode_status == VideoStats.READY:
            logger.warning(
                "忽略转码失败回调，视频已经成功: "
                "video_id=%s, transcode_id=%s",
                data.video_id,
                data.transcode_id,
            )
            return True

        # 转码任务不是当前任务，说明是旧任务回调
        if video.transcode_id != data.transcode_id:
            logger.warning(
                "忽略过期转码失败回调: "
                "video_id=%s, callback_transcode_id=%s, "
                "current_transcode_id=%s",
                data.video_id,
                data.transcode_id,
                video.transcode_id,
            )
            return False

        # 已经失败，重复回调直接幂等返回
        if video.transcode_status == VideoStats.FAILED:
            return True

        video.transcode_status = VideoStats.FAILED
        video.transcode_msg = data.detail
        await self.dao.update(video)
        await self.dao.write_db.commit()

        return True
