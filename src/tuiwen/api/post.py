#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:56
    @Desc: 
=================================================
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, status, Request, Body, Depends, Path, Query, Response

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_post_service
from src.tuiwen.models import PageResponse
from src.tuiwen.post.models import Post, PostCreate, PostRightStatusUpdate
from src.tuiwen.service.post import PostService

router_post = APIRouter(prefix="/posts", tags=[Tag.post])
# 不需要认证的路由
router_public = APIRouter(prefix="/posts",  tags=[Tag.post])


@router_post.post("/", summary="发布帖子", response_model=Post, status_code=status.HTTP_201_CREATED)
async def create_post(post: Annotated[PostCreate, Body(..., description="帖子信息")],
                      request: Annotated[Request, "请求对象"],
                      svc: PostService = Depends(get_post_service)):
    post_data = post.model_dump(exclude={"from_ip", "post_id"})
    # 提取ip地址
    client_ip = None
    if request.client:
        client_ip = request.client.host
    instance = Post(**post_data, from_ip=client_ip, post_id=str(uuid.uuid7()))
    result = await svc.create(instance)
    return result

@router_post.get("/{post_id}/", summary="返回指定的帖子", response_model=Post)
async def get_post(post_id: Annotated[uuid.UUID, "帖子唯一标识"],
                   svc: PostService = Depends(get_post_service)):
    # 构建查询
    statement = select(Post).where(Post.post_id == post_id)
    instance = (await session.exec(statement)).first()

    return instance

@router_public.get("/s/{post_id}/", summary="返回公开的指定的帖子", response_model=Post)
async def get_s_post(post_id: Annotated[uuid.UUID, "帖子唯一标识"],
                     svc: PostService = Depends(get_post_service)):
    # 构建查询
    statement = select(Post).where(Post.post_id == post_id, Post.right_status == RightStatusEnum.PUBLIC)
    instance = (await session.exec(statement)).first()

    return instance


@router_post.get("/latest/", summary="返回最近十条帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts_latest(request: Annotated[Request, "请求对象"],
                           svc: PostService = Depends(get_post_service)):

    dataset = await svc.get_posts_latest(request.state.account_id)
    return PageResponse(items=dataset, total=len(dataset))


@router_post.get("/accounts/{account_id}/", summary="返回指定用户的所有帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_account_posts(account_id: Annotated[str, Path(..., description="用户ID")],
                            request: Annotated[Request, "请求对象"],
                            limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100,
                                                                            description="每页数量(1-100)"),
                            cursor: Annotated[uuid.UUID | None, "数据最旧的ID"] = Query(None),
                            svc: PostService = Depends(get_post_service)
                            ):

    dataset = await svc.get_account_posts(account_id=request.state.account_id, limit=limit, post_id=cursor)

    return PageResponse(items=dataset, total=len(dataset))


@router_post.get("/", summary="返回帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts(request: Annotated[Request, "请求对象"],
                    limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    cursor: Annotated[uuid.UUID | None, "数据最旧的那个post_id"] = Query(None),
                    svc: PostService = Depends(get_post_service)
                    ):

    dataset = await svc.get_posts(request.state.account_id, cursor, limit)

    return PageResponse(items=dataset, total=len(dataset))


@router_post.put('/{post_id}/right/', summary="更新帖子的公开状态", status_code=status.HTTP_205_RESET_CONTENT)
async def update_post_right(post_id: Annotated[uuid.UUID, "帖子ID"],
                            post_right: Annotated[PostRightStatusUpdate, Body(..., description="权限信息")],
                            request: Annotated[Request, "请求对象"],
                            svc: PostService = Depends(get_post_service)):
    await svc.update_post_right(post_id, request.state.account_id, post_right)

    return Response(status_code=status.HTTP_205_RESET_CONTENT)


@router_post.delete("/{post_id}/", summary="删除指定的帖子", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(request: Annotated[Request, "请求对象"],
                      post_id: Annotated[uuid.UUID, Path(..., description="帖子ID")],
                      svc: PostService = Depends(get_post_service)):
    return await svc.delete_by_post_id(post_id,request.state.account_id)
