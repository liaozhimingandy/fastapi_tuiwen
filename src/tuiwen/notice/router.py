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

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_session
from src.tuiwen.models import PageResponse
from src.tuiwen.notice.models import Notice

router_notice = APIRouter(prefix="/notices", tags=[Tag.more])

# 获取系统通知
@router_notice.get("/system/", summary="返回公告通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_system_notices(session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
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

    stmt = select(Notice).where(Notice.type == 1)
    dataset = (await session.exec(stmt)).all()

    return PageResponse(items=dataset, total=len(dataset))

@router_notice.get("/accounts/{account_id}/", summary="返回指定用户的通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_account_notices(acccount_id: Annotated[str, "用户id"], session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    stmt = select(Notice).where(Notice.account_id == acccount_id)
    dataset = (await session.exec(stmt)).all()

    return PageResponse(items=dataset, total=len(dataset))

if __name__ == "__main__":
    pass
