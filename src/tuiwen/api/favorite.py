#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： favorite.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/29
    @Desc: 收藏 API 路由层 —— 收藏 / 取消收藏 / 收藏数查询 / 收藏列表
=================================================
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, status, Request, Depends, HTTPException, Path, Query

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_favorite_service
from src.tuiwen.model.favorite import Favorite, FavoriteCreate, FavoriteCountModel
from src.tuiwen.model.post import Post
from src.tuiwen.models import PageResponse
from src.tuiwen.service.favorite import FavoriteService

router_favorite = APIRouter(prefix="/favorites", tags=[Tag.favorite])


@router_favorite.post('/', summary="收藏", response_model=Favorite, status_code=status.HTTP_201_CREATED)
async def create_favorite(payload: Annotated[FavoriteCreate, "收藏的输入对象"],
                          request: Annotated[Request, "请求对象"],
                          svc: FavoriteService = Depends(get_favorite_service)):
    """
    对目标对象(目前仅帖子)收藏

    Args:
        payload: 收藏入参, 含 target_id(目标对象ID) / target_type(目标对象类型)
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 收藏业务服务

    Returns:
        Favorite: 落库后的收藏记录
    """
    # 收藏人取自令牌, 不接受客户端传入; 重复收藏由联合唯一索引兜底并转成 409
    instance = Favorite(**payload.model_dump(), account_id=request.state.account_id)
    try:
        return await svc.create(instance)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router_favorite.delete('/{target_id}/', summary='取消收藏', status_code=status.HTTP_204_NO_CONTENT)
async def delete_favorite(target_id: Annotated[uuid.UUID, "对象ID"], request: Annotated[Request, "请求对象"],
                          target_type: Annotated[int, Query(ge=1, le=2, description="对象类型 1帖子/2视频")] = 1,
                          svc: FavoriteService = Depends(get_favorite_service)):
    """
    取消当前登录用户对某对象的收藏

    Args:
        target_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        target_type: 对象类型(1帖子/2视频), 避免误删同 ID 其它类型的记录
        svc: 收藏业务服务

    Returns:
        bool: 是否取消到记录(204 无响应体)
    """
    affected = await svc.delete_favorite(target_id, request.state.account_id, target_type=target_type)
    # 事务出口: DELETE 由 DAO 执行但不提交, 这里统一提交
    await svc.dao.commit()
    return affected


@router_favorite.get('/{target_id}/count/', summary="获取指定对象的收藏数", response_model=FavoriteCountModel)
async def get_favorite_count(target_id: Annotated[uuid.UUID, "对象id"], request: Annotated[Request, "请求对象"],
                             target_type: Annotated[int, Query(ge=1, le=2, description="对象类型 1帖子/2视频")] = 1,
                             svc: FavoriteService = Depends(get_favorite_service)) -> FavoriteCountModel:
    """
    查询某对象的收藏总数, 以及当前登录用户是否已收藏

    Args:
        target_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        target_type: 对象类型(1帖子/2视频)
        svc: 收藏业务服务

    Returns:
        FavoriteCountModel: count=收藏总数, is_favorited=当前用户是否已收藏
    """
    result = await svc.get_favorite_count(target_id, request.state.account_id, target_type=target_type)
    return FavoriteCountModel(count=result["favorite_count"], is_favorited=result["is_favorited"])


@router_favorite.get("/account/{account_id}/", summary="返回指定用户收藏过的帖子",
                     response_model=PageResponse[Post], response_model_include={'items', 'total'})
async def get_favorited_posts(account_id: Annotated[uuid.UUID, Path(..., description="用户ID")],
                              request: Annotated[Request, "请求对象"],
                              limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100,
                                                                              description="每页数量(1-100)"),
                              cursor: Annotated[uuid.UUID | None, "数据最旧的ID"] = Query(None),
                              svc: FavoriteService = Depends(get_favorite_service)):
    """
    分页查询某用户收藏过的帖子(按游标向前翻页)

    可见范围: 仅号主本人可见私密收藏, 其他查看者只看公开帖(收藏夹默认不公开)。
    通过 tw_favorite 反查得到收藏记录, 再 JOIN 帖子表返回帖子本体。

    Args:
        account_id: 目标账户ID(要看谁收藏过的内容)
        request: 请求对象, 含当前登录用户
        limit: 每页数量, 1~100
        cursor: 游标, 取上一页最旧一条的 post_id, 为空表示第一页
        svc: 收藏业务服务

    Returns:
        PageResponse[Post]: 帖子列表与总数
    """
    dataset = await svc.get_favorited_posts(account_id=account_id, cursor=cursor, limit=limit,
                                            viewer_account_id=request.state.account_id)
    return PageResponse(items=dataset, total=len(dataset))
