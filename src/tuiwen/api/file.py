"""
文件上传 API 路由层

职责:
    1. 校验上传文件的类型(后缀白名单来自配置 ALLOWED_IMAGE_FORMATS)
    2. 交由 UploadService 落盘 + 记录引用(相同 MD5 直接复用, 避免重复存储)

接口清单:
    POST /api/v2/v2/upload/image/  图片上传

分层位置:
    API → UploadService → UploadDAO → PostgreSQL (+ 本地存储)
"""
from typing import Annotated

from fastapi import APIRouter, status, UploadFile, HTTPException, Depends, Request

from src.tuiwen.dependencies import get_upload_service
from src.tuiwen.service.file import FileService
from src.tuiwen.core import Settings
from src.tuiwen.model.file import FileBase
from src.tuiwen.core import Tag
from src.tuiwen.utils import allowed_file
from src.tuiwen.core import get_settings

# NOTE: 沿用历史前缀, 实际对外路径为 /api/v2/upload/image/
router_upload = APIRouter(prefix="/upload", tags=[Tag.upload])


@router_upload.post('/image/', summary="图片上传", response_model=FileBase, status_code=status.HTTP_201_CREATED)
async def upload_image(file: Annotated[UploadFile, "图片文件"],
                       request: Request,
                       settings: Annotated[Settings, "全局的设置对象"] = Depends(get_settings),
                       svc: FileService = Depends(get_upload_service)):
    """
    上传单张图片

    Args:
        file: multipart/form-data 中的文件字段
        settings: 全局配置对象, 提供允许的图片后缀白名单
        svc: 上传业务服务

    Returns:
        FileBase: image_url(可访问地址) + image_md5(内容指纹, 用于前端去重/秒传判断)
        :param svc:
        :param settings:
        :param file:
        :param request:
    """
    # 检查文件类型
    if not allowed_file(file, file_type=settings.ALLOWED_IMAGE_FORMATS.split(",")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"invalid file type. Only {settings.ALLOWED_IMAGE_FORMATS} images are allowed.")

    return await svc.upload(file, uploader_account_id=request.state.account_id)

