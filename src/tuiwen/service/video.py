"""视频业务服务。

覆盖三条业务线:
    upload             —— 流式接收上传、服务端重算 MD5、按 MD5 去重(秒传)、建记录
    feed               —— 推荐流游标分页, 拼装播放地址与封面地址
    transcode_*        —— 转码服务的完成/失败回调, 幂等更新转码状态

存储约定(与 utils/video_transcoder.py 保持一致):
    <VIDEO_STORAGE_DIR>/<YYYYMM>/<video_id>/original.mp4
    <VIDEO_STORAGE_DIR>/<YYYYMM>/<video_id>/play_list.m3u8
    <VIDEO_STORAGE_DIR>/<YYYYMM>/<video_id>/cover.jpg
    <VIDEO_STORAGE_DIR>/<YYYYMM>/<video_id>/<清晰度>/index.m3u8
"""
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.tuiwen import get_settings
from src.tuiwen.common.feed_cursor import FeedCursor
from src.tuiwen.core.storage import Storage
from src.tuiwen.core.storage import storage
from src.tuiwen.dal.video_source import VideoSourceDAO
from src.tuiwen.model.video import Video, VideoOrientation, VideoTranscodeStatus, VideoFeedResponse, VideoInteraction, \
    VideoAuthor, VideoStats, VideoFeedItem, VideoSource, VideoSourceType, TranscodeCompleteRequest, TranscodeFailedRequest
from src.tuiwen.dal.video import VideoDAO
from src.tuiwen.common.exceptions import BizError
from src.tuiwen.utils import logger
from src.tuiwen.utils.datetime_utils import iso_utc, to_business_tz, utcnow


@dataclass
class VideoService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。

    like_dao/comment_dao/favorite_dao/follow_dao 用于 feed 装配真实互动计数
    (点赞数/评论数/已赞/已收藏/已关注); 任一为 None 时对应字段回退默认值,
    保持单测与既有调用方可不注入。
    """

    dao: VideoDAO
    source_dao: VideoSourceDAO
    like_dao: object | None = None
    comment_dao: object | None = None
    favorite_dao: object | None = None
    follow_dao: object | None = None
    account_dao: object | None = None
    chunk_size: int = 1024 * 1024  # 1MB 分片，可调整
    storage: Storage = storage

    @staticmethod
    def _calc_orientation(width: int, height: int) -> VideoOrientation:
        """由宽高判定画面方向, 返回 VideoOrientation 枚举值。

        上传时源视频宽高未知, 因此在转码完成回调里按回调宽高写入 Video.orientation,
        feed 接口据此返回给前端决定播放器布局。
        """
        if width <= 0 or height <= 0:
            return VideoOrientation.UNKNOWN
        return VideoOrientation.LANDSCAPE if width > height else VideoOrientation.PORTRAIT

    @staticmethod
    def _build_play_url(video: Video) -> str:
        """拼 HLS 播放地址: <URL前缀>/<YYYYMM>/<video_id>/play_list.m3u8。

        与 utils/video_transcoder.py 的实际产物保持一致:
        master playlist 落在视频根目录, 各清晰度在 <清晰度>/index.m3u8,
        播放器拿到 master 后自适应选码率。
        """
        ym = to_business_tz(video.created_at).strftime("%Y%m")
        return (
            f"{get_settings().VIDEO_STORAGE_URL_PREFIX}/"
            f"{ym}/"
            f"{video.id}/"
            f"play_list.m3u8"
        )

    @staticmethod
    def _build_poster_url(video: Video) -> str:
        """拼封面地址: <URL前缀>/<YYYYMM>/<video_id>/cover.jpg。

        文件名与 VideoTranscoder.create_cover 的输出(cover.jpg)保持一致。
        """
        ym = to_business_tz(video.created_at).strftime("%Y%m")
        return (
            f"{get_settings().VIDEO_STORAGE_URL_PREFIX}/"
            f"{ym}/"
            f"{video.id}/"
            f"cover.jpg"
        )

    async def upload(
            self,
            upload_file,
            max_size: int,
            title: str | None,
            description: str | None,
            category: int | None,
            uploader_account_id: uuid.UUID | None = None,
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
                id=video_id,
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
                    "upload_at": iso_utc(utcnow()),
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
                   cursor: Optional[str] = None,
                   viewer_id: Optional[uuid.UUID] = None) -> VideoFeedResponse:
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
                cursor_create_at=decoded.created_at,
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
        items = await self._build_items(videos, viewer_id)

        # 生成下一页 Cursor
        next_cursor = None
        if has_more and videos:
            last_video = videos[-1]

            next_cursor = FeedCursor.encode(
                feed_id=feed_id,
                created_at=last_video.created_at,
                id=last_video.id,
            )

        return VideoFeedResponse(
            feed_id=feed_id,
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def _build_items(self, videos: list[Video],
                           viewer_id: Optional[uuid.UUID]) -> list[VideoFeedItem]:
        """把一页 Video 装配成 feed 条目, 互动计数走批量查询(每类一条 SQL)。

        Args:
            videos: 本页视频实体
            viewer_id: 当前登录用户; None(未登录)时互动状态全为 False

        Returns:
            list[VideoFeedItem]: 携带真实点赞数/评论数与互动状态的条目
        """
        from src.tuiwen.model.like import Like
        from src.tuiwen.model.favorite import Favorite
        from src.tuiwen.model.comment import Comment

        video_ids = [video.id for video in videos]
        author_ids = list({video.account_id for video in videos if video.account_id})

        # --- 批量统计: 每类一条聚合 SQL, 避免逐条 N+1 ---
        like_counts: dict = {}
        comment_counts: dict = {}
        favorite_counts: dict = {}
        liked_ids: set = set()
        collected_ids: set = set()
        followed_ids: set = set()

        if self.like_dao is not None:
            like_counts = await self.like_dao.count_by_targets(Like.TargetTypeEnum.VIDEO, video_ids)
            liked_ids = await self.like_dao.liked_target_ids(viewer_id, Like.TargetTypeEnum.VIDEO, video_ids)
        if self.comment_dao is not None:
            comment_counts = await self.comment_dao.count_by_targets(Comment.TargetTypeEnum.VIDEO, video_ids)
        if self.favorite_dao is not None:
            favorite_counts = await self.favorite_dao.count_by_targets(Favorite.TargetTypeEnum.VIDEO, video_ids)
            collected_ids = await self.favorite_dao.favorited_target_ids(viewer_id, Favorite.TargetTypeEnum.VIDEO, video_ids)
        if self.follow_dao is not None:
            followed_ids = await self.follow_dao.followed_account_ids(viewer_id, author_ids)

        # --- 作者信息: 一条 IN 查询批量装配(头像/昵称), 前端侧栏与底部文案展示用 ---
        authors: dict = {}
        if self.account_dao is not None and author_ids:
            for account in await self.account_dao.get_by_ids(author_ids):
                authors[account.id] = account

        items = []
        for video in videos:
            stats = VideoStats(
                like_count=int(like_counts.get(video.id, 0)),
                comment_count=int(comment_counts.get(video.id, 0)),
                favorite_count=int(favorite_counts.get(video.id, 0)),
            )
            interaction = VideoInteraction(
                liked=video.id in liked_ids,
                collected=video.id in collected_ids,
                followed=bool(video.account_id and video.account_id in followed_ids),
            )
            acc = authors.get(video.account_id) if video.account_id else None
            author = None
            if acc is not None:
                author = VideoAuthor(
                    account_id=acc.id,
                    nickname=acc.nickname or acc.username,
                    avatar_url=acc.avatar,
                )
            items.append(VideoFeedItem(
                video_id=video.id,
                poster_url=self._build_poster_url(video),
                play_url=self._build_play_url(video),
                width=video.width,
                height=video.height,
                duration=video.duration,
                orientation=video.orientation,
                title=video.title,
                description=video.description,
                author=author,
                stats=stats,
                interaction=interaction,
            ))
        return items

    async def follow_feed(self, viewer_id: uuid.UUID, feed_id: Optional[str] = None,
                          limit: int = 10, cursor: Optional[str] = None) -> VideoFeedResponse:
        """关注流: 关注对象的视频 + 自己的视频(游标分页, 需登录)。

        Args:
            viewer_id: 当前登录用户
            feed_id: 本次浏览会话 ID(首页传 None 新建)
            limit: 每页条数
            cursor: 上一页返回的续读游标

        Returns:
            VideoFeedResponse: 与推荐流同构的响应
        """
        if cursor:
            try:
                decoded = FeedCursor.decode(cursor)
            except ValueError:
                raise BizError(code=400, message="无效的分页游标")
            feed_id = decoded.feed_id
            videos = await self.dao.get_follow_feed(
                viewer_id,
                cursor_create_at=decoded.created_at,
                cursor_id=decoded.id,
                limit=limit + 1,
            )
        else:
            feed_id = feed_id or uuid.uuid7()
            videos = await self.dao.get_follow_feed(viewer_id, limit=limit + 1)

        has_more = len(videos) > limit
        if has_more:
            videos = videos[:limit]

        items = await self._build_items(videos, viewer_id)

        next_cursor = None
        if has_more and videos:
            last_video = videos[-1]
            next_cursor = FeedCursor.encode(
                feed_id=feed_id,
                created_at=last_video.created_at,
                id=last_video.id,
            )

        return VideoFeedResponse(
            feed_id=feed_id,
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def transcode_complete(self, data: TranscodeCompleteRequest) -> bool:
        """处理转码完成回调: 回写转码状态/时长/宽高/方向, 并按清晰度落 VideoSource。

        幂等与顺序保护:
            已成功 → 直接返回 True(重复回调无害)
            记录上已有 transcode_id 且与回调不一致 → 旧任务, 返回 False
            (transcode_id 为 NULL 视为"首个任务", 直接接受;
             等转码任务提交逻辑落地后, 提交时会先回填 transcode_id 再进入转码)

        Args:
            data: TranscodeCompleteRequest, 含 video_id / transcode_id / variants 等

        Returns:
            bool: True 已处理; False 旧任务回调被忽略

        Raises:
            BizError: 视频不存在 / 回调的变体列表为空
        """
        video = await self.dao.get_by_unique_field("id", data.video_id)

        if video is None:
            raise BizError(
                f"视频不存在: {data.video_id}"
            )

        # 已经成功，重复回调直接幂等返回
        if video.transcode_status == VideoTranscodeStatus.SUCCESS:
            return True

        # 不是当前转码任务(记录上还没回填 transcode_id 时视为首个任务, 放行)
        if video.transcode_id is not None and video.transcode_id != data.transcode_id:
            logger.warning(
                "忽略旧转码任务回调: video_id=%s, callback_transcode_id=%s, current_transcode_id=%s",
                data.video_id,
                data.transcode_id,
                video.transcode_id,
            )
            return False

        if not data.variants:
            raise BizError(
                "转码结果为空"
            )

        sources = [
            VideoSource(
                video_id=video.id,
                source_type=VideoSourceType.HLS,
                quality=item.quality,
                url=item.url,
                size=item.size,
                bitrate=item.bitrate,
            )
            for item in data.variants
        ]

        video.transcode_status = VideoTranscodeStatus.SUCCESS
        video.transcode_id = data.transcode_id
        video.duration = int(data.duration)  # 表字段为整型秒, 回调给的是浮点, 向下取整
        video.width = data.width
        video.height = data.height
        video.orientation = self._calc_orientation(data.width, data.height)
        video.transcode_msg = None

        await self.dao.complete_transcode(video=video)
        # 幂等保护: 先清掉该视频的旧源记录再写, 保证回调重放不会撞 (video_id,type,quality) 唯一约束
        await self.source_dao.delete_by_fields(video_id=video.id)
        await self.source_dao.bulk_create(sources)
        await self.source_dao.commit()
        await self.dao.write_db.commit()

        return True

    async def transcode_failed(self, data: TranscodeFailedRequest,) -> bool:
        """处理转码失败回调: 记录失败原因, 但不覆盖已成功的记录。

        幂等与顺序保护与 transcode_complete 一致:
            已成功 → 忽略失败回调(返回 True, 告知转码服务无需重试)
            已失败 → 重复回调幂等返回 True
            transcode_id 不一致(且记录上已有值) → 旧任务, 返回 False

        Args:
            data: 失败详情, 含 video_id / transcode_id / detail

        Returns:
            bool: True 已处理(含幂等忽略); False 旧任务回调被忽略

        Raises:
            BizError: 视频不存在
        """
        video = await self.dao.get_by_unique_field("id", data.video_id)

        if video is None:
            raise BizError(f"视频不存在: {data.video_id}")

        # 已经成功，不允许失败回调覆盖 SUCCESS
        if video.transcode_status == VideoTranscodeStatus.SUCCESS:
            logger.warning(
                "忽略转码失败回调，视频已经成功: "
                "video_id=%s, transcode_id=%s",
                data.video_id,
                data.transcode_id,
            )
            return True

        # 转码任务不是当前任务，说明是旧任务回调
        if video.transcode_id is not None and video.transcode_id != data.transcode_id:
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
        if video.transcode_status == VideoTranscodeStatus.FAILED:
            return True

        video.transcode_status = VideoTranscodeStatus.FAILED
        video.transcode_id = data.transcode_id
        video.transcode_msg = data.detail[:128]  # 表字段 max_length=128, 截断防止入库报错
        await self.dao.update(video)
        await self.dao.write_db.commit()

        return True
