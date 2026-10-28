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
from src.tuiwen.model.snap import Snap, SnapCreate
from src.tuiwen.service.snap import SnapService

router_public = APIRouter(prefix='/snaps', tags=[Tag.more])


def _client_timezone(request: Request) -> str | None:
    """
    读取客户端上报的时区(浏览器 `Intl.DateTimeFormat().resolvedOptions().timeZone`)

    「天亮即焚」的场次是按**用户本地墙钟** 23:00~06:00 判定的, 所以服务端必须知道
    请求方在哪个时区, 否则全球用户只能统一按北京时间开闸。

    Args:
        request: 当前请求对象

    Returns:
        str | None: IANA 时区名(如 `America/New_York`); 未上报时为 None,
                    由 service 层回退到业务时区

    NOTE: 这个头来自客户端, 不可信; 校验与兜底在 `snap_service.resolve_timezone` 里做,
          这里只负责取值, 不在这里抛异常。
    """
    return request.headers.get("x-timezone")


@router_public.post("/", response_model=Snap, status_code=201, summary="天亮即焚提交")
async def create_snap(
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
async def get_snaps_latest(request: Request, svc: SnapService = Depends(get_snap_service)):
    """
    获取最新的 10 条快照(首页信息流)

    Args:
        request: 请求对象, 从中取 `X-Timezone` 决定场次窗口按哪个时区计算
        svc: 快照业务服务

    Returns:
        PageResponse[Snap]: 快照列表与总数
    """
    result = await svc.get_snaps_latest(tz_name=_client_timezone(request))
    return PageResponse(items=result.items, total=result.total)


@router_public.get("/", summary="返回快照列表", response_model=PageResponse[Snap],
                   response_model_include={'items', 'total'})
async def get_snaps(request: Request,
                    limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    offset: Annotated[int, "偏移量, 从 0 开始"] = Query(0, ge=0),
                    svc: SnapService = Depends(get_snap_service)
                    ):
    """
    分页获取快照列表

    Args:
        request: 请求对象, 从中取 `X-Timezone` 决定场次窗口按哪个时区计算
        limit: 每页数量, 1~100
        offset: 偏移量, 从 0 开始

    Returns:
        PageResponse[Snap]: 快照列表与总数

    NOTE: offset 原来默认是 1, 导致第一页永远跳过最新的一条; 语义也不是
          "最旧的那个 id"(那是游标), 这里统一成标准偏移量语义。
    """
    result = await svc.get_snaps(limit=limit, offset=offset, tz_name=_client_timezone(request))
    return PageResponse(items=result.items, total=result.total)


# 点赞是写操作, 必须用 POST: 原来用 GET 既不符合语义, 也会被浏览器/网关预取命中
@router_public.post("/{pk}/like/", summary="快照点赞")
async def snap_like(pk: Annotated[int, '快照主键id'], svc: SnapService = Depends(get_snap_service)):
    """
    给指定快照点赞(次数 +1)

    Args:
        pk: 快照主键 id
        svc: 快照业务服务

    Returns:
        dict: success=是否成功, like_count=最新点赞数
    """
    _count = await svc.inc_snaps_like(pk)
    return {"success": True, "like_count": _count}
