#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： notice.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 11:30
    @Desc: 通知 API 路由层 —— 系统公告 / 指定用户通知 查询
=================================================
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, HTTPException, status

from src.tuiwen.service.notice import NoticeService
from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_notice_service
from src.tuiwen.models import PageResponse
from src.tuiwen.model.notice import Notice, NoticeReadPayload


router_notice = APIRouter(prefix="/notices", tags=[Tag.more])


# 获取系统通知
@router_notice.get("/system/", summary="返回公告通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_system_notices(svc: NoticeService = Depends(get_notice_service),
                             page: int = Query(default=1, ge=1),
                             size: int = Query(default=10, ge=1, le=20), ):
    """
    分页获取系统公告类通知

    Args:
        svc: 通知业务服务
        page: 页码, 从 1 开始
        size: 每页数量, 1~20

    Returns:
        PageResponse[Notice]: 公告列表与总数

    ### 通知类型 NoticeType
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | SYSTEM | 0 | 系统通知 |
    | LIKE | 1 | 点赞 |
    | COMMENT | 2 | 评论 |
    | FOLLOW | 3 | 关注 |
    | MENTION | 4 | @提及 |

    ### 关联资源类型 NoticeTargetType
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | POST | 1 | 帖子 |
    | COMMENT | 2 | 评论 |
    | USER | 3 | 用户 |

    ### 推送范围 NoticeTargetScope
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | ALL | 1 | 全部用户 |
    | NEW_USER | 2 | 新用户 |
    | VIP | 3 | 付费VIP用户 |
    """

    # 页码 → 偏移量换算, 统一在 API 层完成
    result = await svc.get_system_notices(limit=size, offset=(page - 1) * size)
    return PageResponse(items=result.items, total=result.total)


@router_notice.get("/accounts/{account_id}/", summary="返回指定用户的通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_account_notices(account_id: Annotated[uuid.UUID, "用户id"],
                              request: Annotated[Request, "请求对象"],
                              svc: NoticeService = Depends(get_notice_service),
                              page: int = Query(default=1, ge=1),
                              size: int = Query(default=20, ge=1, le=100),
                              notice_type: Annotated[int | None, Query(ge=0, le=4)] = None):
    """
    分页获取某个用户收到的通知(按创建时间倒序)

    Args:
        account_id: 用户账户唯一标识
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 通知业务服务
        page: 页码, 从 1 开始
        size: 每页数量, 1~100
        notice_type: 通知类型过滤(0系统/1点赞/2评论/3关注/4提及), 不传返回全部

    Returns:
        PageResponse[Notice]: 通知列表与总数

    Raises:
        HTTPException: 403 —— 试图查看别人的通知

    说明: 通知属于私密数据, 必须限定只能看自己的; 原实现任意登录用户
          改一下路径里的 account_id 就能读到别人的通知。
    """
    if request.state.account_id != account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能查看自己的通知")

    result = await svc.get_user_notices(account_id, limit=size, offset=(page - 1) * size,
                                        notice_type=notice_type)
    return PageResponse(items=result.items, total=result.total)


@router_notice.get("/accounts/{account_id}/unread-count/", summary="返回指定用户的未读通知数",
                   tags=[Tag.more])
async def get_unread_count(account_id: Annotated[uuid.UUID, "用户id"],
                           request: Annotated[Request, "请求对象"],
                           svc: NoticeService = Depends(get_notice_service)):
    """
    统计某个用户收到的未读通知数

    Raises:
        HTTPException: 403 —— 试图查看别人的通知
    """
    if request.state.account_id != account_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能查看自己的通知")
    return {"count": await svc.unread_count(account_id)}


@router_notice.put("/read/", summary="批量标记通知为已读", tags=[Tag.more])
async def mark_notices_read(payload: Annotated[NoticeReadPayload, "已读入参"],
                            request: Annotated[Request, "请求对象"],
                            svc: NoticeService = Depends(get_notice_service)):
    """
    把当前登录用户的通知批量标记为已读

    Args:
        payload: ids 为空/缺省时表示全部标记已读

    Returns:
        dict: {"marked": 实际标记的行数}
    """
    marked = await svc.mark_read(request.state.account_id, ids=payload.ids)
    return {"marked": marked}


if __name__ == "__main__":
    pass
