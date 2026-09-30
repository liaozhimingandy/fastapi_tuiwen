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
from fastapi.params import Form, File

from src.tuiwen.dependencies import get_video_service
from src.tuiwen.service.video import VideoService
from src.tuiwen.model.video import Video
from src.tuiwen.core import Settings
from src.tuiwen.core import Tag
from src.tuiwen.utils import allowed_file
from src.tuiwen.core import get_settings

# NOTE: 沿用历史前缀, 实际对外路径为 /api/v2/upload/image/
router_upload = APIRouter(prefix="/upload", tags=[Tag.upload])


@router_upload.post('/video/', summary="视频", response_model=Video, status_code=status.HTTP_201_CREATED)
async def upload_video(
        request: Request,
        file: Annotated[UploadFile, File(description="视频文件，支持mp4等格式")],
        title: Annotated[str | None, Form(max_length=200)] = None,
        description: Annotated[str | None, Form()] = None,
        category: Annotated[int | None, Form()] = None,
        video_md5: Annotated[str | None, Form()] = None,
        settings: Annotated[Settings, "全局的设置对象"] = Depends(get_settings),
        svc: VideoService = Depends(get_video_service)):
    """
    上传视频文件
    Args:
        file: multipart/form-data 视频文件
        request: 请求对象，携带登录账号信息
        settings: 全局配置对象，文件大小、后缀白名单
        svc: 视频业务服务
    Returns:
        Video: 视频主表记录
    """

    # 基础参数校验
    # ✅ 修复你原代码int第二个参数错误问题
    MAX_SIZE = settings.VIDEO_MAX_BYTES or 100 * 1024 * 1024  # 默认100MB

    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    # 校验后缀白名单
    allow_suffix = settings.VIDEO_ALLOW_SUFFIX.split(",") or (".mp4", ".mov", ".mkv")
    filename = file.filename.lower()
    suffix = filename[filename.rfind("."):] if "." in filename else ""

    if suffix not in allow_suffix:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式，允许：{allow_suffix}")

    try:
        return await svc.upload(file, uploader_account_id=getattr(request.state, "account_id", "1"), title=title,
                            description=description, video_md5=video_md5,
                            category=category, max_size=MAX_SIZE)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
