from typing import Annotated

from fastapi import APIRouter, status, UploadFile, HTTPException, Depends

from src.tuiwen.dependencies import get_upload_service
from src.tuiwen.service.upload import UploadService
from src.tuiwen.core import Settings
from src.tuiwen.post.models import ImageBase
from src.tuiwen.core import Tag
from src.tuiwen.utils import allowed_file
from src.tuiwen.core import get_settings

router_upload = APIRouter(prefix="/v2/upload", tags=[Tag.upload])


@router_upload.post('/image/', summary="图片上传", response_model=ImageBase, status_code=status.HTTP_201_CREATED)
async def upload_image(file: Annotated[UploadFile, "图片文件"],
                       settings: Annotated[Settings, "全局的设置对象"] = Depends(get_settings),
                       svc: UploadService = Depends(get_upload_service)):
    # 检查文件类型
    if not allowed_file(file, file_type=settings.ALLOWED_IMAGE_FORMATS.split(",")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"invalid file type. Only {settings.ALLOWED_IMAGE_FORMATS} images are allowed.")

    instance = await svc.upload(file)

    return ImageBase(image_url=instance.image_url, image_md5=image_md5)