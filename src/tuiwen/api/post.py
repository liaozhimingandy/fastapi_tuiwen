#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： post.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 21:56
    @Desc: 帖子 API 路由层 —— 发布 / 详情 / 列表 / 可见性 / 删除
=================================================
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, status, Request, Body, Depends, Path, Query, Response

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_post_service
from src.tuiwen.models import PageResponse
from src.tuiwen.model.post import Post, PostCreate, PostRightStatusUpdate
from src.tuiwen.service.post import PostService

router_post = APIRouter(prefix="/posts", tags=[Tag.post])
# 不需要认证的路由
router_public = APIRouter(prefix="/posts",  tags=[Tag.post])


@router_post.post("/", summary="发布帖子", response_model=Post, status_code=status.HTTP_201_CREATED)
async def create_post(post: Annotated[PostCreate, Body(..., description="帖子信息")],
                      request: Annotated[Request, "请求对象"],
                      svc: PostService = Depends(get_post_service)):
    """
    发布一条帖子

    Args:
        post: 帖子入参(标题/正文/可见性等)
        request: 请求对象, 用于提取来源 IP
        svc: 帖子业务服务

    Returns:
        Post: 落库后的帖子实体

    说明:
        post_id 使用 uuid7(时间有序), 由服务端生成;
        from_ip 由服务端从请求中提取, 不接受客户端传入。
    """
    post_data = post.model_dump(exclude={"from_ip"})
    # 提取ip地址
    client_ip = None
    if request.client:
        client_ip = request.client.host
    instance = Post(**post_data, from_ip=client_ip, id=uuid.uuid7())
    result = await svc.create(instance)
    return result


@router_post.get("/{post_id}/", summary="返回指定的帖子", response_model=Post)
async def get_post(post_id: Annotated[uuid.UUID, "帖子唯一标识"],
                   svc: PostService = Depends(get_post_service)):
    """
    查询指定帖子(需登录)

    Args:
        post_id: 帖子唯一标识
        svc: 帖子业务服务

    Returns:
        Post | None: 帖子实体, 不存在时返回 None
    """
    instance = await svc.get_post(post_id)
    return instance


@router_public.get("/s/{post_id}/", summary="返回公开的指定的帖子", response_model=Post)
async def get_s_post(post_id: Annotated[uuid.UUID, "帖子唯一标识"],
                     svc: PostService = Depends(get_post_service)):
    """
    匿名查询公开(right_status=PUBLIC)的帖子详情

    Args:
        post_id: 帖子唯一标识
        svc: 帖子业务服务

    Returns:
        Post | None: 仅当帖子为公开状态时返回实体, 否则 None
    """
    # 构建查询
    instance = await svc.get_s_post(post_id)
    return instance


@router_post.get("/latest/", summary="返回最近十条帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts_latest(request: Annotated[Request, "请求对象"],
                           svc: PostService = Depends(get_post_service)):
    """
    获取最近 10 条帖子

    可见范围: 公开帖子 + 自己发布的全部帖子

    Args:
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 帖子业务服务

    Returns:
        PageResponse[Post]: 帖子列表与总数
    """
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
    """
    分页查询某个用户的帖子(按游标向前翻页)

    Args:
        account_id: 目标用户 ID(路径参数)
        request: 请求对象, 含当前登录用户
        limit: 每页数量, 1~100
        cursor: 游标, 取上一页最旧一条的 post_id, 为空表示第一页
        svc: 帖子业务服务

    Returns:
        PageResponse[Post]: 帖子列表与总数
    """

    # account_id 是「要看谁的主页」, viewer account_id 是「谁在看」, 两者相同才包含私密帖
    dataset = await svc.get_account_posts(account_id=account_id, cursor=cursor, limit=limit,
                                          viewer_account_id=request.state.account_id)

    return PageResponse(items=dataset, total=len(dataset))


@router_post.get("/", summary="返回帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts(request: Annotated[Request, "请求对象"],
                    limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    cursor: Annotated[uuid.UUID | None, "数据最旧的那个post_id"] = Query(None),
                    svc: PostService = Depends(get_post_service)
                    ):
    """
    分页获取帖子流(公开帖子 + 自己的帖子)

    Args:
        request: 请求对象, request.state.account_id 由认证依赖写入
        limit: 每页数量, 1~100
        cursor: 游标, 上一页最旧一条的 post_id
        svc: 帖子业务服务

    Returns:
        PageResponse[Post]: 帖子列表与总数
    """

    dataset = await svc.get_posts(request.state.account_id, cursor, limit)

    return PageResponse(items=dataset, total=len(dataset))


@router_post.put('/{post_id}/right/', summary="更新帖子的公开状态", status_code=status.HTTP_205_RESET_CONTENT)
async def update_post_right(post_id: Annotated[uuid.UUID, "帖子ID"],
                            post_right: Annotated[PostRightStatusUpdate, Body(..., description="权限信息")],
                            request: Annotated[Request, "请求对象"],
                            svc: PostService = Depends(get_post_service)):
    """
    修改帖子的可见性(公开 / 私密)

    仅帖子的所有者可修改, 由 DAO 层的 post_id + account_id 双条件保证。

    Args:
        post_id: 帖子 ID
        post_right: 新的可见性状态
        request: 请求对象, 用于取当前登录用户
        svc: 帖子业务服务

    Returns:
        Response: 205 Reset Content
    """
    # Service/DAO 期望的是 int 枚举值, 这里取模型字段而不是整个模型对象
    await svc.update_post_right(post_id, request.state.account_id, post_right.right_status)
    # 事务出口: DAO 只执行 UPDATE, 由 API 层统一提交
    await svc.dao.commit()

    return Response(status_code=status.HTTP_205_RESET_CONTENT)


@router_post.delete("/{post_id}/", summary="删除指定的帖子", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(request: Annotated[Request, "请求对象"],
                      post_id: Annotated[uuid.UUID, Path(..., description="帖子ID")],
                      svc: PostService = Depends(get_post_service)):
    """
    删除指定帖子(硬删除)

    Args:
        request: 请求对象, 用于取当前登录用户
        post_id: 帖子 ID
        svc: 帖子业务服务

    Returns:
        bool: 是否删除了记录(204 无响应体)
    """
    affected = await svc.delete_by_post_id(post_id, request.state.account_id)
    # 事务出口: DAO 只执行 DELETE, 由 API 层统一提交
    await svc.dao.commit()
    return affected
