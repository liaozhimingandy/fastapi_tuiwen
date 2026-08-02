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

router_notice = APIRouter(prefix="/notices", tags=[Tag.notifications])

# 获取系统通知
@router_notice.get("/system/", summary="返回公告通知", response_model=PageResponse[Notice],
                   response_model_include={'items', 'total'})
async def get_system_notices(session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
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
