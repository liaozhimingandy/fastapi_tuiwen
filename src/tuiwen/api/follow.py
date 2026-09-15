import uuid
from typing import Annotated

from fastapi import APIRouter, Body, status, Depends, Request, Path, Query

from src.tuiwen.dependencies import get_follow_service
from src.tuiwen.service.follow import FollowService
from src.tuiwen.post.models import Follow, FollowCountModel

router_follow = APIRouter(prefix="/follows", tags=["follow"])


@router_follow.post('/', summary="关注", response_model=Follow, status_code=status.HTTP_201_CREATED)
async def follow(follow: Annotated[Follow, Body(..., description="关注信息")],
                 svc: FollowService = Depends(get_follow_service)) -> Follow:
    follow_data = follow.model_dump(exclude={"id", "create_at"})
    instance = Follow(**follow_data)

    return await svc.create(instance)


@router_follow.delete('/{follower_id}/{followee_id}/', summary="取消关注", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow(follower_id: Annotated[str, "追随者ID"], followee_id: Annotated[str, "被关注者ID"],
                        svc: FollowService = Depends(get_follow_service)):
    return await svc.delete(follower_id=follower_id, followee_id=followee_id)


@router_follow.get('/{account_id}/count/', summary="获取指定帐户的关注和正在关注数量及获赞数量",
                   response_model=FollowCountModel)
async def get_follow_info_by_id(account_id: Annotated[str, "账户ID"], request: Annotated[Request, "请求对象"],
                                svc: FollowService = Depends(get_follow_service)) -> FollowCountModel:
    """
    获取指定帐户的关注和正在关注数量及获赞数量

    - **account_id**: 平台账号唯一标识
    """
    result = await svc.get_follow_info_by_id(account_id)

    return FollowCountModel(**result)