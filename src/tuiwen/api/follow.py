"""
关注 API 路由层

职责:
    1. 提供关注/取关/查询关注统计/关注列表/粉丝列表五类接口
    2. 参数校验与响应模型组装, 业务逻辑下沉到 FollowService

接口清单:
    POST   /api/v2/follows/                              关注
    DELETE /api/v2/follows/{followee_id}/                取消关注(关注者取自令牌)
    GET    /api/v2/follows/{account_id}/count/           关注数/粉丝数/获赞数统计
    GET    /api/v2/follows/{account_id}/followees/       关注列表(正在关注谁)
    GET    /api/v2/follows/{account_id}/followers/       粉丝列表(谁关注了他)

分层位置:
    API → FollowService → FollowDAO → PostgreSQL
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, status, Depends, Request, HTTPException, Query

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dependencies import get_follow_service
from src.tuiwen.models import PageResponse
from src.tuiwen.service.follow import FollowService
from src.tuiwen.model.account import AccountInfo
from src.tuiwen.model.follow import Follow, FollowCreate, FollowCountModel

router_follow = APIRouter(prefix="/follows", tags=["follow"])


@router_follow.post('/', summary="关注", response_model=Follow, status_code=status.HTTP_201_CREATED)
async def follow(payload: Annotated[FollowCreate, Body(..., description="关注信息")],
                 request: Annotated[Request, "请求对象"],
                 svc: FollowService = Depends(get_follow_service)) -> Follow:
    """
    建立关注关系

    Args:
        payload: 关注入参, 只需 followee_id(被关注者)
        request: 请求对象, request.state.account_id 由认证依赖写入(关注者)
        svc: 关注业务服务

    Returns:
        Follow: 落库后的关注记录

    Raises:
        HTTPException: 400 —— 关注自己; 409 —— 已经关注过
    """
    # 关注者取自令牌, 不接受客户端传入
    instance = Follow(follower_id=request.state.account_id, followee_id=payload.followee_id)
    try:
        return await svc.create(instance)
    except BizError as e:
        raise HTTPException(status_code=e.code, detail=e.message)


@router_follow.delete('/{followee_id}/', summary="取消关注", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow(followee_id: Annotated[uuid.UUID, "被关注者ID"],
                        request: Annotated[Request, "请求对象"],
                        svc: FollowService = Depends(get_follow_service)):
    """
    取消关注关系(硬删除)

    Args:
        followee_id: 被关注者账户ID
        request: 请求对象, request.state.account_id 由认证依赖写入(关注者)
        svc: 关注业务服务

    Returns:
        bool: 是否删除了记录(204 无响应体)

    NOTE: 路径里不再接收 follower_id —— 原来任何人都能按 (follower_id, followee_id)
          删掉别人之间的关注关系。关注者只能是自己。
    """
    affected = await svc.delete(follower_id=request.state.account_id, followee_id=followee_id)
    # 事务出口: DELETE 由 DAO 执行但不提交, 这里统一提交
    await svc.dao.commit()
    return affected


@router_follow.get('/{account_id}/count/', summary="获取指定帐户的关注和正在关注数量及获赞数量",
                   response_model=FollowCountModel)
async def get_follow_info_by_id(account_id: Annotated[uuid.UUID, "账户ID"], request: Annotated[Request, "请求对象"],
                                svc: FollowService = Depends(get_follow_service)) -> FollowCountModel:
    """
    获取指定帐户的关注和正在关注数量及获赞数量

    - **account_id**: 平台账号唯一标识
    """
    # viewer(当前登录用户)用于判断"我是否已关注该账户", 不再误用自关注记录
    result = await svc.get_follow_info_by_id(account_id, viewer_id=request.state.account_id)

    # 展开为强类型响应模型, 避免直接暴露内部字典结构
    return FollowCountModel(**result)


@router_follow.get('/{account_id}/followees/', summary="获取指定账户的关注列表",
                   response_model=PageResponse[AccountInfo])
async def list_followees(account_id: Annotated[uuid.UUID, "账户ID"],
                         svc: FollowService = Depends(get_follow_service),
                         page: Annotated[int, Query(ge=1)] = 1,
                         size: Annotated[int, Query(ge=1, le=50)] = 20) -> PageResponse[AccountInfo]:
    """
    获取指定账户正在关注的账号列表(按关注时间倒序)

    - **account_id**: 平台账号唯一标识
    """
    items, total = await svc.list_followees(account_id, offset=(page - 1) * size, limit=size)
    return PageResponse(items=items, total=total, page_size=size)


@router_follow.get('/{account_id}/followers/', summary="获取指定账户的粉丝列表",
                   response_model=PageResponse[AccountInfo])
async def list_followers(account_id: Annotated[uuid.UUID, "账户ID"],
                         svc: FollowService = Depends(get_follow_service),
                         page: Annotated[int, Query(ge=1)] = 1,
                         size: Annotated[int, Query(ge=1, le=50)] = 20) -> PageResponse[AccountInfo]:
    """
    获取关注指定账户的粉丝列表(按关注时间倒序)

    - **account_id**: 平台账号唯一标识
    """
    items, total = await svc.list_followers(account_id, offset=(page - 1) * size, limit=size)
    return PageResponse(items=items, total=total, page_size=size)
