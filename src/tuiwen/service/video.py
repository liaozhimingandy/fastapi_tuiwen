import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.storage import Storage
from src.tuiwen.core.storage import Storage
from src.tuiwen.core.storage import storage
from src.tuiwen.service.storage import storage
from src.tuiwen.common.snowflake import gen_snowflake_id
from src.tuiwen.model.video import Video, VideoOrientation
from src.tuiwen.dal.video import VideoDAO
from src.tuiwen.common.exceptions import BizError


@dataclass
class VideoService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。
    """

    dao: VideoDAO
    chunk_size: int = 1024 * 1024  # 1MB 分片，可调整
    storage: Storage = storage

    @staticmethod
    def _calc_orientation(width: int, height: int) -> int:
        if width <= 0 or height <= 0:
            return VideoOrientation.UNKNOWN
        return VideoOrientation.LANDSCAPE if width > height else VideoOrientation.PORTRAIT

    async def upload(self, upload_file, max_size: int,  title, description, category,
                     uploader_account_id: str = '1', file_md5_front: Optional[str] = None):
        """流式上传，不一次性加载全部文件到内存
        :param upload_file
        :param file_md5_front: 前端传过来的md5（precheck用）

        """
        # 1. 如果前端携带md5，优先预查重（秒传）
        if file_md5_front:
            instance = await self.dao.get_by_unique_field('video_md5', file_md5_front)
            if instance:
                return instance

        # 2. 初始化md5计算器，准备流式写入本地临时文件
        md5_obj = hashlib.md5()
        video_id = gen_snowflake_id()
        filename = upload_file.filename or ""
        ext = os.path.splitext(filename.lower())[1] or ".mp4"

        # 临时文件路径（先写到临时目录，全部接收完再移动到正式目录）
        temp_dir = Path("/data/video/tmp/")
        temp_dir.mkdir(exist_ok=True)
        temp_file_path = temp_dir / f"{video_id}{ext}"
        total_bytes = 0

        try:
            # 流式循环读取分片
            with open(temp_file_path, "wb") as f:
                async for chunk in upload_file.iter_chunked(self.chunk_size):
                    total_bytes += len(chunk)
                    # 文件大小超限立刻终止
                    if total_bytes > max_size:
                        raise BizError(code=413, message=f"文件不能超过 {max_size / 1024 / 1024:.2f}MB")
                    md5_obj.update(chunk)
                    f.write(chunk)

            if total_bytes == 0:
                raise BizError(code=400, message="文件为空")

            file_md5 = md5_obj.hexdigest()

            # 3. 二次兜底查重（防止前端伪造md5）
            instance = await self.dao.get_by_unique_field('video_md5', file_md5)
            if instance:
                # 命中重复，删除临时文件，直接返回已有记录
                os.unlink(temp_file_path)
                return instance

            # 4. 移动临时文件到正式存储目录
            final_key = await self.storage.save(video_id, upload_file) # type: ignore
            file_url = await self.storage.url(final_key)

            # 5. ffprobe同步拿宽高时长
            # meta = get_video_meta(full_local_path)
            # width = meta.get("width", 0)
            # height = meta.get("height", 0)
            # duration = meta.get("duration", 0)
            # orientation = self.calc_orientation(width, height)

            # 6. 入库
            video = Video(
                video_id=video_id,
                poster=None,
                title=title,
                description=description,
                category=category,
                default_url=file_url,
                account_id=uploader_account_id,
                video_md5=file_md5,
                extra={
                    "original_filename": filename,
                    "storage_key": file_url,
                    "size_bytes": total_bytes,
                    "content_type": upload_file.content_type,
                    "file_suffix": ext,
                    "upload_at": datetime.utcnow().isoformat()
                }
            )
            instance = await self.dao.create(video)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)

            # 投递转码后台任务
            # transcode_task.delay(video_id, file_url, full_local_path)
            return instance
        except Exception:
            # 异常清理临时文件
            if temp_file_path.exists():
                os.unlink(temp_file_path)
            raise
