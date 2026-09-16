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
from typing import Annotated

from fastapi import APIRouter, status, Request, Depends

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_like_service
from src.tuiwen.model.like import LikeInput, Like, LikeCountModel
from src.tuiwen.service.like import LikeService

router_like = APIRouter(prefix="/likes", tags=[Tag.like])


@router_like.post('/', summary="点赞", response_model=Like, status_code=status.HTTP_201_CREATED)
async def create_like(payload: Annotated[LikeInput, "赞的输入对象"],
                      svc: LikeService = Depends(get_like_service)):
    """
    对目标对象(目前仅帖子)点赞

    Args:
        payload: 点赞入参, 含 obj_id(目标对象ID) / obj_type(目标对象类型)
        svc: 点赞业务服务

    Returns:
        Like: 落库后的点赞记录
    """
    instance = Like(
        **payload.model_dump(exclude={})
    )
    result = await svc.create(instance)
    return result


@router_like.delete('/{obj_id}/', summary='取消赞', status_code=status.HTTP_204_NO_CONTENT)
async def delete_like(obj_id: Annotated[str, "对象ID"], request: Annotated[Request, "请求对象"],
                      svc: LikeService = Depends(get_like_service)):
    """
    取消当前登录用户对某对象的点赞

    Args:
        obj_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 点赞业务服务

    Returns:
        bool: 是否取消到记录(204 无响应体)
    """
    affected = await svc.delete_like(obj_id, request.state.account_id)
    # 事务出口: DELETE 由 DAO 执行但不提交, 这里统一提交
    await svc.dao.commit()
    return affected


@router_like.get('/{obj_id}/count/', summary="获取指定帖子的点赞数", response_model=LikeCountModel)
async def get_like_count(obj_id: Annotated[str, "对象id"], request: Annotated[Request, "请求对象"],
                         svc: LikeService = Depends(get_like_service)) -> LikeCountModel:
    """
    查询某对象的点赞总数, 以及当前登录用户是否已点赞

    Args:
        obj_id: 目标对象 ID
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 点赞业务服务

    Returns:
        LikeCountModel: count=点赞总数, is_liked=当前用户是否已点赞
    """
    # Service/DAO 返回的是 dict, 不是对象, 必须用下标访问
    result = await svc.get_like_count(obj_id, request.state.account_id)
    return LikeCountModel(count=result["like_count"], is_liked=result["is_liked"])
