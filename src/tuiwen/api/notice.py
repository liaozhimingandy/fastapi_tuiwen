#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： router.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 11:30
    @Desc:
=================================================
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.tuiwen.service.notice import NoticeService
from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_notice_dao, get_notice_service
from src.tuiwen.models import PageResponse
from src.tuiwen.notice.models import Notice


router_notice = APIRouter(prefix="/v2/notices", tags=[Tag.more])


# 获取系统通知
@router_notice.get("/system/", summary="返回公告通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_system_notices(svc: NoticeService = Depends(get_notice_service),
                             page: int = Query(default=1,ge=1),
                             size: int = Query(default=10,ge=1,le=20),):
    """
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

    result = await svc.get_system_notices(limit=size, offset=(page-1)*size)
    return PageResponse(items=result.items, total=result.total)

@router_notice.get("/accounts/{account_id}/", summary="返回指定用户的通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_account_notices(account_id: Annotated[str, "用户id"], svc: NoticeService = Depends(get_notice_service),
                              page: int = Query(default=1,ge=1), size: int = Query(default=20,ge=1,le=100),):
    result = await svc.get_user_notices(account_id, limit=size, offset=(page-1)*size)
    return PageResponse(items=result.items, total=len(result.items))


if __name__ == "__main__":
    pass
