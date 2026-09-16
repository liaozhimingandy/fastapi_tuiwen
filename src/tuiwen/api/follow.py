"""
关注 API 路由层

职责:
    1. 提供关注/取关/查询关注统计三类接口
    2. 参数校验与响应模型组装, 业务逻辑下沉到 FollowService

接口清单:
    POST   /api/v2/follows/                              关注
    DELETE /api/v2/follows/{follower_id}/{followee_id}/  取消关注
    GET    /api/v2/follows/{account_id}/count/           关注数/粉丝数/获赞数统计

分层位置:
    API → FollowService → FollowDAO → PostgreSQL
"""
from typing import Annotated

from fastapi import APIRouter, Body, status, Depends, Request, HTTPException

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dependencies import get_follow_service
from src.tuiwen.service.follow import FollowService
from model.follow import Follow, FollowCountModel

router_follow = APIRouter(prefix="/follows", tags=["follow"])


@router_follow.post('/', summary="关注", response_model=Follow, status_code=status.HTTP_201_CREATED)
async def follow(follow: Annotated[Follow, Body(..., description="关注信息")],
                 svc: FollowService = Depends(get_follow_service)) -> Follow:
    """
    建立关注关系

    Args:
        follow: 关注关系入参, 核心字段为 follower_id(关注者)与 followee_id(被关注者)
        svc: 关注业务服务

    Returns:
        Follow: 落库后的关注记录
    """
    # 主键 id 与创建时间由数据库/模型负责生成, 不接受客户端传入
    follow_data = follow.model_dump(exclude={"id", "create_at"})
    instance = Follow(**follow_data)
    try:
        return await svc.create(instance)
    except BizError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router_follow.delete('/{follower_id}/{followee_id}/', summary="取消关注", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow(follower_id: Annotated[str, "追随者ID"], followee_id: Annotated[str, "被关注者ID"],
                        svc: FollowService = Depends(get_follow_service)):
    """
    取消关注关系(硬删除)

    Args:
        follower_id: 关注者账户ID
        followee_id: 被关注者账户ID
        svc: 关注业务服务

    Returns:
        bool: 是否删除了记录(204 无响应体)
    """
    affected = await svc.delete(follower_id=follower_id, followee_id=followee_id)
    # 事务出口: DELETE 由 DAO 执行但不提交, 这里统一提交
    await svc.dao.commit()
    return affected


@router_follow.get('/{account_id}/count/', summary="获取指定帐户的关注和正在关注数量及获赞数量",
                   response_model=FollowCountModel)
async def get_follow_info_by_id(account_id: Annotated[str, "账户ID"], request: Annotated[Request, "请求对象"],
                                svc: FollowService = Depends(get_follow_service)) -> FollowCountModel:
    """
    获取指定帐户的关注和正在关注数量及获赞数量

    - **account_id**: 平台账号唯一标识
    """
    result = await svc.get_follow_info_by_id(account_id)

    # 展开为强类型响应模型, 避免直接暴露内部字典结构
    return FollowCountModel(**result)
