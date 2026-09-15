#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： snap.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/9/14 20:04
    @Desc: 「天亮即焚」快照 API 路由层(公开接口) —— 发布 / 列表 / 点赞
=================================================
"""
from typing import Annotated

from fastapi import APIRouter, Request, Depends, Query

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_snap_service
from src.tuiwen.models import PageResponse
from src.tuiwen.more.models import Snap, SnapCreate
from src.tuiwen.service.snap import SnapService

router_public = APIRouter(prefix='/snaps', tags=[Tag.more])


@router_public.post("/", response_model=Snap, status_code=201, summary="天亮即焚提交")
async def creat_snaps(
        payload: Annotated[SnapCreate, "内容"],
        request: Annotated[Request, "请求对象"],
        svc: SnapService = Depends(get_snap_service),
):
    """
    发布一条「天亮即焚」内容

    Args:
        payload: 内容入参(正文 + 情绪标识)
        request: 请求对象, 用于提取来源 IP
        svc: 快照业务服务

    Returns:
        Snap: 落库后的快照实体

    # 情绪枚举值
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | NONE | 0 | 未选择情绪 |
    | INSOMNIA | 1 | 失眠 |
    | WRONGED | 2 | 委屈 |
    | HEARTBEAT | 3 | 心动 |
    | RELAX | 4 | 放空 |
    | COMPLAIN | 5 | 吐槽 |
    | HAPPY | 6 | 开心 |
    | SAD | 7 | 难过 |
    | LONELY | 8 | 孤独 |
    | ANXIOUS | 9 | 焦虑 |
    | CONFUSED | 10 | 迷茫 |
    | ANGRY | 11 | 生气 |
    | TIRED | 12 | 疲惫 |
    | TOUCHED | 13 | 感动 |
    | GUILTY | 14 | 愧疚 |
    | HOPEFUL | 15 | 抱有期待 |
    """

    # 排除服务端生成的字段(主键/来源IP), 避免客户端伪造
    instance = Snap(
        **payload.model_dump(exclude={"from_ip", "id"})
    )

    # 提取ip地址
    client_ip = None
    if request.client:
        client_ip = request.client.host

    instance.from_ip = client_ip

    return await svc.create_snap(instance)


@router_public.get("/latest/", response_model=PageResponse[Snap], summary="获取最新的十条数据")
async def get_snaps_latest(svc: SnapService = Depends(get_snap_service)):
    """
    获取最新的 10 条快照(首页信息流)

    Args:
        svc: 快照业务服务

    Returns:
        PageResponse[Snap]: 快照列表与总数
    """
    result = await svc.get_snaps_latest()
    return PageResponse(items=result.items, total=result.total)


@router_public.get("/", summary="返回帖子", response_model=PageResponse[Snap],
                   response_model_include={'items', 'total'})
async def get_snaps(limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    offset: Annotated[int | None, "数据最旧的那个id"] = Query(1, ge=0),
                    svc: SnapService = Depends(get_snap_service)
                    ):
    """
    分页获取快照列表

    Args:
        limit: 每页数量, 1~100
        offset: 偏移量, 从 0 开始
        svc: 快照业务服务

    Returns:
        PageResponse[Snap]: 快照列表与总数
    """
    result = await svc.get_snaps(limit=limit, offset=offset)
    return PageResponse(items=result.items, total=result.total)


@router_public.get("/{pk}/like/", summary="帖子点赞")
async def snaps_like(pk: Annotated[int, '帖子id'], svc: SnapService = Depends(get_snap_service)):
    """
    给指定快照点赞(次数 +1)

    Args:
        pk: 快照主键 id
        svc: 快照业务服务

    Returns:
        dict: success=是否成功, like=最新点赞数
    """
    _count = await svc.inc_snaps_like(pk)
    return {"success": True, "like": _count}
