"""视频 API 路由层。

职责:
    1. 视频上传: 校验后缀白名单/大小上限后交给 VideoService 流式落盘
    2. 推荐流: 游标分页返回待播放的 HLS 视频列表
    3. 转码回调: 接收转码服务的完成/失败通知(内部接口)

接口清单(实际对外路径带 /api/v2 前缀):
    POST /api/v2/videos/upload/                       视频上传
    GET  /api/v2/videos/feed/                         推荐流
    POST /api/v2/videos/internal/transcode-complete/  转码完成回调
    POST /api/v2/videos/internal/transcode-failed/    转码失败回调

分层位置:
    API → VideoService → VideoDAO / VideoSourceDAO → PostgreSQL (+ 本地存储)
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, status, UploadFile, HTTPException, Depends, Request
from fastapi.params import Form, File, Query

from src.tuiwen.dependencies import get_video_service, get_optional_account_id
from src.tuiwen.service.video import VideoService
from src.tuiwen.common.exceptions import BizError
from src.tuiwen.model.video import Video, VideoFeedQuery, VideoFeedResponse, TranscodeCompleteRequest, \
    TranscodeFailedRequest, VideoCategory, MyVideoItem
from src.tuiwen.core import Settings
from src.tuiwen.core import Tag
from src.tuiwen.utils import allowed_file
from src.tuiwen.core import get_settings

# NOTE: 路由前缀为 /videos, 拼上 /api/v2 后实际路径是 /api/v2/videos/*
router_upload = APIRouter(prefix="/videos", tags=[Tag.upload])


@router_upload.post('/upload/', summary="视频", response_model=Video, status_code=status.HTTP_201_CREATED)
async def upload_video(
        file: Annotated[UploadFile, File(description="视频文件，支持mp4等格式")],
        title: Annotated[str | None, Form(max_length=200)] = None,
        description: Annotated[str | None, Form()] = None,
        category: Annotated[VideoCategory | None, Form(description="时长分类 1短视频 2中视频 3长视频")] = None,
        video_md5: Annotated[str | None, Form()] = None,
        settings: Annotated[Settings, "全局的设置对象"] = Depends(get_settings),
        uploader_account_id: Annotated[uuid.UUID | None, "上传者(可选认证)"] = Depends(get_optional_account_id),
        svc: VideoService = Depends(get_video_service)):
    """
    上传视频文件

    处理顺序: 文件名/后缀白名单校验 → 交给 Service 流式写盘(边读边算 MD5)
    → Service 内做去重判断、建 Video 记录并投递转码任务。

    注意最大长度等参数由 Form/File 声明约束, FastAPI 会先做一轮校验再进函数体。

    Args:
        file: multipart/form-data 视频文件
        title/description/category: 视频元信息, 均可选
        video_md5: 前端预计算的 MD5, 仅用于「秒传」预检查, 不作为入库依据
        settings: 全局配置对象，文件大小、后缀白名单
        uploader_account_id: 上传者账户ID; 本路由免登录, 带合法令牌才有值
        svc: 视频业务服务

    Returns:
        Video: 视频主表记录

    Raises:
        HTTPException: 400 —— 文件名为空、后缀不在白名单、或 Service 抛出的业务异常
    """

    # 基础参数校验
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
        return await svc.upload(file, uploader_account_id=uploader_account_id, title=title,
                                description=description, video_md5=video_md5,
                                category=category, max_size=MAX_SIZE)
    except BizError as e:
        # 业务异常: 按 Service 约定的业务码透传(如 413 超限 / 400 空文件)
        raise HTTPException(status_code=e.code, detail=e.message)
    except HTTPException:
        raise
    except Exception as e:
        # 非业务异常(存储/数据库等): 保留 500 语义, 不再一律压成 400, 便于排查
        raise HTTPException(status_code=500, detail=f"视频上传失败: {e}")


@router_upload.get('/feed/', summary="返回推荐流", response_model=VideoFeedResponse,
                   status_code=status.HTTP_200_OK)
async def feed(request: Request,
               query: Annotated[VideoFeedQuery, Query()],
               viewer_id: Annotated[uuid.UUID | None, "浏览者(可选认证)"] = Depends(get_optional_account_id),
               svc: VideoService = Depends(get_video_service)):
    """返回推荐流(游标分页)。

    Args:
        request: 请求对象(当前未使用, 预留后续按账号做个性化)
        query: 查询参数, 含 feed_id / cursor / limit(1~20)
        viewer_id: 浏览者账户ID; 登录时用于装配「已赞/已收藏/已关注」互动态
        svc: 视频业务服务

    Returns:
        VideoFeedResponse: 本页视频列表 + 下一页游标 + has_more
    """
    return await svc.feed(feed_id=query.feed_id, limit=query.limit, cursor=query.cursor,
                          viewer_id=viewer_id)


@router_upload.get('/mine/', summary="返回我的视频列表", response_model=list[MyVideoItem],
                   status_code=status.HTTP_200_OK)
async def my_videos(uploader_account_id: Annotated[uuid.UUID | None, "当前用户(可选认证)"] = Depends(get_optional_account_id),
                    offset: Annotated[int, "偏移量"] = Query(0, ge=0),
                    limit: Annotated[int, "每页数量"] = Query(12, ge=1, le=50),
                    svc: VideoService = Depends(get_video_service)):
    """返回当前登录用户的视频列表(含转码中/失败, 按时间倒序)。

    「我的视频」页数据源; 未登录返回 401。

    Args:
        uploader_account_id: 当前登录用户; None 表示未登录
        offset: 偏移量
        limit: 每页数量, 1~50
        svc: 视频业务服务

    Returns:
        list[MyVideoItem]: 视频列表(带转码状态与互动计数)
    """
    if uploader_account_id is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return await svc.my_videos(uploader_account_id, limit=limit, offset=offset)


@router_upload.get('/follow/', summary="返回关注流", response_model=VideoFeedResponse,
                   status_code=status.HTTP_200_OK)
async def follow_feed(request: Request,
                      query: Annotated[VideoFeedQuery, Query()],
                      viewer_id: Annotated[uuid.UUID | None, "浏览者(可选认证)"] = Depends(get_optional_account_id),
                      svc: VideoService = Depends(get_video_service)):
    """返回关注流(关注对象的视频 + 自己的视频, 游标分页)。

    注意必须注册在 /{video_id}/ 之前(若有同类路径参数路由), 否则 "follow" 会被
    当作 uuid 参数解析。当前 videos 前缀下没有 /{video_id}/ 路由, 仍按此顺序放置。

    Raises:
        HTTPException: 401 —— 未登录(关注流是登录态能力)
    """
    if viewer_id is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return await svc.follow_feed(viewer_id, feed_id=query.feed_id, limit=query.limit,
                                 cursor=query.cursor)


@router_upload.post("/internal/transcode-complete/", response_model=bool,)
async def transcode_complete(
    data: TranscodeCompleteRequest,
    svc: VideoService = Depends(get_video_service),
):
    """转码完成回调(内部接口, 由转码服务调用)。

    幂等设计: 已成功直接返回 True; transcode_id 与记录不一致视为旧任务, 返回 False。

    NOTE: 内部接口当前挂在 router_public(免登录), 上线前建议加内部调用鉴权
          (共享密钥头或仅允许内网访问), 否则任何人都能伪造转码结果。

    Args:
        data: 转码结果(视频 ID、任务 ID、时长、宽高、各清晰度产物)
        svc: 视频业务服务

    Returns:
        bool: True 已接受; False 旧任务回调被忽略
    """
    return await svc.transcode_complete(data)


@router_upload.post("/internal/transcode-failed/", response_model=bool,)
async def transcode_failed(
    data: TranscodeFailedRequest,
    service: VideoService = Depends(get_video_service),
) -> bool:
    """转码失败回调(内部接口, 由转码服务调用)。

    幂等设计: 已成功的不允许被失败回调覆盖(返回 True 表示"已确认, 无需重试");
    transcode_id 不匹配视为旧任务, 返回 False。

    Args:
        data: 失败详情(视频 ID、任务 ID、失败原因)
        service: 视频业务服务

    Returns:
        bool: True 已处理; False 旧任务回调被忽略
    """
    return await service.transcode_failed(data)