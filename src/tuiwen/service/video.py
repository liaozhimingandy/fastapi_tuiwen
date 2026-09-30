import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.tuiwen import get_settings
from src.tuiwen.core.storage import Storage
from src.tuiwen.core.storage import storage
from src.tuiwen.common.snowflake import gen_snowflake_id
from src.tuiwen.model.video import Video, VideoOrientation, VideoTranscodeStatus
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

    async def upload(self, upload_file, max_size: int, title, description, category,
                     uploader_account_id: str = '1', video_md5: Optional[str] = None):
        """流式上传，不一次性加载全部文件到内存
        :param max_size:
        :param category:
        :param description:
        :param title:
        :param uploader_account_id:
        :param upload_file
        :param video_md5: 前端传过来的md5（precheck用）
        相同md5文件复用底层存储，但每个用户生成独立视频记录
        """
        # 标记：是否命中已有文件（不需要再上传存储）
        hit_exist_file: Optional[str] = None
        # 1. 如果前端携带md5，预查重
        if video_md5:
            # 查找任意一条拥有该md5的记录，拿存储地址，不直接return
            instance = await self.dao.get_one(video_md5=video_md5, account_id=uploader_account_id)
            if instance:
                hit_exist_file = instance.default_url
                return instance

        # 2. 初始化md5计算器
        md5_obj = hashlib.md5()
        video_id = uuid.uuid7() # gen_snowflake_id()
        filename = upload_file.filename or ""
        ext = os.path.splitext(filename.lower())[1] or ".mp4"

        temp_dir = Path(get_settings().VIDEO_STORAGE_DIR, 'tmp')
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file_path = temp_dir / f"{video_id}{ext}"
        total_bytes = 0

        try:
            # 流式读取分片，计算md5，写入临时文件
            with open(temp_file_path, "wb") as f:
                while True:
                    chunk = await upload_file.read(self.chunk_size)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_size:
                        raise BizError(code=413, message=f"文件不能超过 {max_size / 1024 / 1024:.2f}MB")
                    md5_obj.update(chunk)
                    f.write(chunk)

            if total_bytes == 0:
                raise BizError(code=400, message="文件为空")

            file_md5 = md5_obj.hexdigest()
            # 3. 二次兜底查重：看是否已经存在该md5的文件资源
            file_instance = await self.dao.get_one(video_md5=file_md5, account_id=uploader_account_id)
            if file_instance:
                hit_exist_file = file_instance.default_url

            # 4. 判断：复用已有文件 还是 上传新文件到存储
            if hit_exist_file:
                # ✅ 文件已经存在，跳过storage上传，直接复用存储地址
                file_url = hit_exist_file
                # 临时文件不再需要，直接删除
                temp_file_path.unlink(missing_ok=True)
            else:
                # 文件不存在，执行上传到storage
                upload_file.file.seek(0)
                final_key = await self.storage.save(str(video_id), upload_file, ext)
                file_url = await self.storage.url(final_key)

            # 6. 入库：新建独立视频记录！！不管md5是否重复，都新建tw_video
            video = Video(
                video_id=video_id,
                poster=None,
                title=title,
                description=description,
                category=category,
                default_url=file_url,
                account_id=uploader_account_id,
                video_md5=file_md5,
                transcode_status=VideoTranscodeStatus.PENDING,
                transcode_msg=None,
                is_deleted=False,
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

            # 删除临时文件
            temp_file_path.unlink(missing_ok=True)
            # 投递转码任务（注意：相同md5文件只需要转码一次，这里你可以加判断）
            # transcode_task.delay(video_id, file_url)
            return instance
        except Exception:
            if temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)
            raise
        finally:
            await upload_file.close()
