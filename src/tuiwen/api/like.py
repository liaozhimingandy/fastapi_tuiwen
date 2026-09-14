#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： like.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:20
    @Desc: 
=================================================
"""
from typing import Annotated

from fastapi import APIRouter, status, Request, Depends

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_like_service
from src.tuiwen.post.models import LikeInput, Like, LikeCountModel
from src.tuiwen.service.like import LikeService

router_like = APIRouter(prefix="/v2/likes", tags=[Tag.like])


@router_like.post('/', summary="点赞", response_model=Like, status_code=status.HTTP_201_CREATED)
async def create_like(payload: Annotated[LikeInput, "赞的输入对象"],
                      svc: LikeService = Depends(get_like_service)):
    instance = Like(
        **payload.model_dump(exclude={})
    )
    result = await svc.dao.create(instance)
    return result


@router_like.delete('/{obj_id}/', summary='取消赞', status_code=status.HTTP_204_NO_CONTENT)
async def delete_like(obj_id: Annotated[str, "对象ID"], request: Annotated[Request, "请求对象"],
                      svc: LikeService = Depends(get_like_service)):
        return await svc.delete_like(obj_id, request.state.account_id)


@router_like.get('/{obj_id}/count/', summary="获取指定帖子的点赞数", response_model=LikeCountModel)
async def get_like_count(obj_id: Annotated[str, "对象id"], request: Annotated[Request, "请求对象"],
                         svc: LikeService = Depends(get_like_service)) -> LikeCountModel:

    result = await svc.get_like_count(obj_id, request.state.account_id)
    return LikeCountModel(count=result.like_count, is_liked=result.is_liked)
