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
from src.tuiwen.model.file import File, FileType, FileStatus


@dataclass
class FileService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。
    """

    dao: FileDAO

    async def upload(self, file, uploader_account_id: uuid.UUID | None = None):
        """
        上传单张图片并返回图片记录

        处理流程:
            读取内容 → 计算 MD5 → 按 MD5 查重 → 不存在则落盘并登记数据库

        Args:
            file: FastAPI 的 UploadFile 对象
            uploader_account_id: 上传者账户ID, 由 API 层从 request.state 取

        Returns:
            File: 文件记录(命中秒传时返回已存在的那条)

        NOTE: 秒传分支(命中 file_md5)不校验 account_id —— 只要内容一致, 任何登录用户
              都能拿到别人那条 File 记录的 url/storage_key。若上传内容是私有素材,
              应按业务决定是否对该分支加归属校验
        NOTE: 没有大小/数量限制, `await file.read()` 会把整个文件读进内存;
              api/file.py 的 allowed_file 只校验了图片格式, ALLOWED_IMAGE_FORMATS 之外
              的体积上限需要另加。大文件建议改流式落盘 + size 阈值校验
        NOTE: 先写磁盘再写库, 若 DB 写入失败会在存储目录留下孤儿文件(反之则不会出现);
              需要严格一致时可改为写临时名 + 提交成功后 rename
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

        # 根据 mime 判断大类与落盘子目录 image / video / audio / doc。
        # 原来这里把 file_type 写死成 1(图片), 而该服务其实也接视频/音频/文档,
        # 导致 tw_file.file_type 永远是 1 —— 现在按 mime 映射到 FileType。
        # NOTE: 默认值里的连字符必须是 ASCII '-'。原写法 "application/octet‑stream" 用的是
        #       U+2011(non-breaking hyphen), 不是合法 MIME 类型
        mime_type = file.content_type or "application/octet-stream"
        if mime_type.startswith("image/"):
            sub_dir, file_type = "images", FileType.IMAGE
        elif mime_type.startswith("video/"):
            sub_dir, file_type = "videos", FileType.VIDEO
        elif mime_type.startswith("audio/"):
            sub_dir, file_type = "audios", FileType.AUDIO
        else:
            sub_dir, file_type = "docs", FileType.DOC

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
            file_type=file_type,
            url=url,
            storage_key=storage_key,
            file_md5=file_md5,
            mime_type=mime_type,
            original_name=original_name,
            file_size=file_size,
            extra={},
            status=FileStatus.ACTIVE,  # 0=临时文件，绑定帖子后改为1正式
        )

        instance = await self.dao.create(new_file)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance
