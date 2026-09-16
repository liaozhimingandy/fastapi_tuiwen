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
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.tuiwen.service.notice import NoticeService
from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_notice_service
from src.tuiwen.models import PageResponse
from model.notice import Notice


# NOTE: 本路由自带 /v2 前缀, 挂在 /api/v2 之下后实际路径为 /api/v2/notices/...
#       与 post 等模块的 /api/v2/xxx 不一致
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
async def get_account_notices(account_id: Annotated[str, "用户id"], svc: NoticeService = Depends(get_notice_service),
                              page: int = Query(default=1, ge=1), size: int = Query(default=20, ge=1, le=100), ):
    """
    分页获取某个用户收到的通知(按创建时间倒序)

    Args:
        account_id: 用户账户唯一标识
        svc: 通知业务服务
        page: 页码, 从 1 开始
        size: 每页数量, 1~100

    Returns:
        PageResponse[Notice]: 通知列表与总数
    """
    result = await svc.get_user_notices(account_id, limit=size, offset=(page - 1) * size)
    return PageResponse(items=result.items, total=len(result.items))


if __name__ == "__main__":
    pass
