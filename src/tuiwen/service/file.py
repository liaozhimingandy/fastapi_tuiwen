"""
文件上传业务服务层(UploadService)

职责:
    1. 读取上传文件内容并计算 MD5
    2. 按 MD5 去重: 已存在则直接复用原记录(秒传)
    3. 不存在则落盘到本地存储目录, 并在数据库登记图片引用

分层位置:
    API → UploadService → UploadDAO → PostgreSQL (+ 本地文件系统)
"""
import hashlib
import os
import uuid
from dataclasses import dataclass

from src.tuiwen.dal.file import FileDAO
from src.tuiwen.core import get_settings
from model.post import File


@dataclass
class FileService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。
    """

    dao: FileDAO

    async def upload(self, file, uploader_account_id: str = 1):
        """
        上传单张图片并返回图片记录

        处理流程:
            读取内容 → 计算 MD5 → 按 MD5 查重 → 不存在则落盘并登记数据库

        Args:
            file: FastAPI 的 UploadFile 对象

        Returns:
            TWImage: 图片记录(image_url / image_name / image_md5)
            :param file:
            :param uploader_account_id:
        """

        contents = await file.read()  # 读取文件内容

        # 计算文件的MD5值
        # 以内容指纹为依据实现「相同图片只存一份」
        md5 = hashlib.md5()
        md5.update(contents)
        file_md5 = md5.hexdigest()

        # 判断文件是否存在
        instance = await self.dao.get_by_unique_field("file_md5", file_md5)

        if instance:
            return instance

        settings = get_settings()

        # 根据mime判断文件类型 image / video / audio / doc
        mime_type = file.content_type or "application/octet‑stream"
        if mime_type.startswith("image/"):
            file_type = "image"
            sub_dir = "images"
        elif mime_type.startswith("video/"):
            file_type = "video"
            sub_dir = "videos"
        elif mime_type.startswith("audio/"):
            file_type = "audio"
            sub_dir = "audios"
        else:
            file_type = "doc"
            sub_dir = "docs"

        upload_dir = f"{settings.STORAGE_LOCAL_ROOT}/{sub_dir}"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir, exist_ok=True)

        # uuid重命名，防御文件名路径穿越
        suffix = os.path.splitext(file.filename)[1] if file.filename else ""
        store_filename = f"{str(uuid.uuid4())}{suffix}"
        file_path = f"{upload_dir}/{store_filename}"

        # 本地磁盘写入二进制
        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        # 对外访问url
        url = f"{settings.STORAGE_URL_PREFIX}/{sub_dir}/{store_filename}"
        # storage_key：本地路径；后续切OSS时改为oss bucket key，业务上层不用大改
        storage_key = f"{sub_dir}/{store_filename}"
        file_size = len(contents)
        original_name = file.filename

        # 组装ORM实体，extra留空；图片宽高/视频时长后续异步回填
        new_file = File(
            account_id=uploader_account_id,
            file_type=1,
            url=url,
            storage_key=storage_key,
            file_md5=file_md5,
            mime_type=mime_type,
            original_name=original_name,
            file_size=file_size,
            extra=None,
            status=1,  # 0=临时文件，绑定帖子后改为1正式
        )

        instance = await self.dao.create(new_file)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance
