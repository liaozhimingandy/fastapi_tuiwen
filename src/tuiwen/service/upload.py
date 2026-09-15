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

from src.tuiwen.dal.upload import UploadDAO
from src.tuiwen.core import get_settings
from src.tuiwen.post.models import Image as TWImage


@dataclass
class UploadService:
    """上传业务服务。

    dao 由依赖注入(get_upload_service)在构造时传入 —— 原实现在类定义处直接
    `dao = UploadDAO()` 实例化, 既没传 write_db / read_db 会话(构造即报错),
    又把 DAO 变成了所有请求共享的类属性, 会造成请求间会话串用。
    """

    dao: UploadDAO

    async def upload(self, file):
        """
        上传单张图片并返回图片记录

        处理流程:
            读取内容 → 计算 MD5 → 按 MD5 查重 → 不存在则落盘并登记数据库

        Args:
            file: FastAPI 的 UploadFile 对象

        Returns:
            TWImage: 图片记录(image_url / image_name / image_md5)
        """

        contents = await file.read()  # 读取文件内容

        # 计算文件的MD5值
        # 以内容指纹为依据实现「相同图片只存一份」
        md5 = hashlib.md5()
        md5.update(contents)
        image_md5 = md5.hexdigest()

        # 判断文件是否存在
        instance = await self.dao.get_by_unique_field("image_md5", image_md5)

        if not instance:
            # 保存到文件
            upload_dir = f"{get_settings().STORAGE_LOCAL_ROOT}/images"
            # 判断文件夹是否存在,不存在则新建
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)

            # 用 uuid 重命名, 避免同名覆盖与用户可控文件名带来的路径穿越风险
            file_name = f'{str(uuid.uuid4())}{os.path.splitext(file.filename)[1]}'
            file_path = f"{upload_dir}/{file_name}"
            with open(file_path, "wb") as buffer:
                buffer.write(contents)

            # 对外可访问的 URL 由配置的静态资源前缀拼接得到
            image_url = f"{get_settings().STORAGE_URL_PREFIX}/images/{file_name}"
            # 保存引用到数据库
            obj = TWImage(image_url=image_url, image_name=file.filename, image_md5=image_md5)
            instance = await self.dao.create(obj)
        return instance
