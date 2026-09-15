import hashlib
import os
import uuid

from src.tuiwen.dal.upload import UploadDAO
from src.tuiwen.core import get_settings
from src.tuiwen.post.models import Image as TWImage


class UploadService:
    dao = UploadDAO()

    async def upload(self, file):


        contents = await file.read()  # 读取文件内容

        # 计算文件的MD5值
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

            file_name = f'{str(uuid.uuid4())}{os.path.splitext(file.filename)[1]}'
            file_path = f"{upload_dir}/{file_name}"
            with open(file_path, "wb") as buffer:
                buffer.write(contents)

            image_url = f"{get_settings().STORAGE_URL_PREFIX}/images/{file_name}"
            # 保存引用到数据库
            obj = TWImage(image_url=image_url, image_name=file.filename, image_md5=image_md5)
            instance = await self.dao.create(obj)
        return instance