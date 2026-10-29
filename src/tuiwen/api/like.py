#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:20
    @Desc: 点赞 API 路由层 —— 点赞 / 取消赞 / 点赞数查询
=================================================
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, status, Request, Depends, HTTPException, Path, Query

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_like_service
from src.tuiwen.model.like import Like, LikeCreate, LikeCountModel
from src.tuiwen.model.post import Post
from src.tuiwen.models import PageResponse
from src.tuiwen.service.like import LikeService

router_like = APIRouter(prefix="/likes", tags=[Tag.like])


@router_like.post('/', summary="点赞", response_model=Like, status_code=status.HTTP_201_CREATED)
async def create_like(payload: Annotated[LikeCreate, "赞的输入对象"],
                      request: Annotated[Request, "请求对象"],
                      svc: LikeService = Depends(get_like_service)):
    """
    对目标对象(目前仅帖子)点赞

    Args:
        payload: 点赞入参, 含 target_id(目标对象ID) / target_type(目标对象类型)
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 点赞业务服务

    Returns:
        Like: 落库后的点赞记录
    """
    # 点赞人取自令牌, 不接受客户端传入; 重复点赞由联合唯一索引兜底并转成 409
    instance = Like(**payload.model_dump(), account_id=request.state.account_id)
    try:
        return await svc.create(instance)
    except BizError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router_like.delete('/{target_id}/', summary='取消赞', status_code=status.HTTP_204_NO_CONTENT)
async def delete_like(target_id: Annotated[uuid.UUID, "对象ID"], request: Annotated[Request, "请求对象"],
                      target_type: Annotated[int, Query(ge=1, le=2, description="对象类型 1帖子/2视频")] = 1,
                      svc: LikeService = Depends(get_like_service)):
    """
    取消当前登录用户对某对象的点赞

    Args:
        target_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        target_type: 对象类型(1帖子/2视频), 避免误删同 ID 其它类型的记录
        svc: 点赞业务服务

    Returns:
        bool: 是否取消到记录(204 无响应体)
    """
    affected = await svc.delete_like(target_id, request.state.account_id, target_type=target_type)
    # 事务出口: DELETE 由 DAO 执行但不提交, 这里统一提交
    await svc.dao.commit()
    return affected


@router_like.get('/{target_id}/count/', summary="获取指定对象的点赞数", response_model=LikeCountModel)
async def get_like_count(target_id: Annotated[uuid.UUID, "对象id"], request: Annotated[Request, "请求对象"],
                         target_type: Annotated[int, Query(ge=1, le=2, description="对象类型 1帖子/2视频")] = 1,
                         svc: LikeService = Depends(get_like_service)) -> LikeCountModel:
    """
    查询某对象的点赞总数, 以及当前登录用户是否已点赞

    Args:
        target_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        target_type: 对象类型(1帖子/2视频)
        svc: 点赞业务服务

    Returns:
        LikeCountModel: count=点赞总数, is_liked=当前用户是否已点赞
    """
    # Service/DAO 返回的是 dict, 不是对象, 必须用下标访问
    result = await svc.get_like_count(target_id, request.state.account_id, target_type=target_type)
    return LikeCountModel(count=result["like_count"], is_liked=result["is_liked"])


@router_like.get("/account/{account_id}/", summary="返回指定用户点赞过的帖子",
                 response_model=PageResponse[Post], response_model_include={'items', 'total'})
async def get_liked_posts(account_id: Annotated[uuid.UUID, Path(..., description="用户ID")],
                          request: Annotated[Request, "请求对象"],
                          limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100,
                                                                          description="每页数量(1-100)"),
                          cursor: Annotated[uuid.UUID | None, "数据最旧的ID"] = Query(None),
                          svc: LikeService = Depends(get_like_service)):
    """
    分页查询某用户点赞过的帖子(按游标向前翻页)

    可见范围与「我的帖子」一致: 仅号主本人可见私密帖, 其他查看者只看公开帖。
    通过 tw_like 反查得到点赞记录, 再 JOIN 帖子表返回帖子本体。

    Args:
        account_id: 目标账户ID(要看谁点赞过的内容)
        request: 请求对象, 含当前登录用户
        limit: 每页数量, 1~100
        cursor: 游标, 取上一页最旧一条的 post_id, 为空表示第一页
        svc: 点赞业务服务

    Returns:
        PageResponse[Post]: 帖子列表与总数
    """
    dataset = await svc.get_liked_posts(account_id=account_id, cursor=cursor, limit=limit,
                                        viewer_account_id=request.state.account_id)
    return PageResponse(items=dataset, total=len(dataset))
