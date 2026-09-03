from typing import Annotated

from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.tuiwen.models import PageResponse
from src.tuiwen.core import Tag, add_instance
from src.tuiwen.dependencies import get_session
from .models import Feedback, FeedbackStatus, FeedbackCreate, FeedbackResponse, SnapCreate, Snap

router_public = APIRouter(tags=[Tag.more])


@router_public.post("/feedbacks/", response_model=FeedbackResponse, status_code=201, summary="提交用户反馈")
async def submit_feedback(
        payload: Annotated[FeedbackCreate, "反馈内容"],
        request: Annotated[Request, "请求对象"],
        session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session),
):
    instance = Feedback(
        **payload.model_dump(),
        account_id=request.state.account_id if request.state else None,
        user_agent=request.headers.get("user-agent"),
        client_ip=request.client.host if request.client else None,
        status=FeedbackStatus.PENDING
    )

    instance = await add_instance(session, instance)

    return instance


@router_public.post("/snaps/", response_model=Snap, status_code=201, summary="天亮即焚提交")
async def creat_snaps(
        payload: Annotated[SnapCreate, "内容"],
        request: Annotated[Request, "请求对象"],
        session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session),
):
    instance = Snap(
        **payload.model_dump(exclude={"from_ip", "id"})
    )

    # 提取ip地址
    client_ip = None
    if request.client:
        client_ip = request.client.host

    instance.from_ip = client_ip

    instance = await add_instance(session, instance)

    return instance


@router_public.get("/snaps/latest/", response_model=PageResponse[Snap], summary="获取最新的十条数据")
async def get_snaps_latest(session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    stmt = select(Snap).order_by(-Snap.id).limit(10)
    dataset = (await session.exec(stmt)).all()

    return PageResponse(items=dataset, total=len(dataset))


@router_public.get("/snaps/", summary="返回帖子", response_model=PageResponse[Snap],
                 response_model_include={'items', 'total'})
async def get_snaps(limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    cursor: Annotated[int | None, "数据最旧的那个id"] = Query(1, gt=0),
                    session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)
                    ):
    # 构建查询（保持UTC时间比较）
    statement = select(Snap).where(Snap.id > cursor)

    # 按创建时间倒序 + 限制数量
    statement = statement.order_by(-Snap.id).limit(limit)

    dataset = (await session.exec(statement)).all()

    return PageResponse(items=dataset, total=len(dataset))


@router_public.get("/snaps/{id}/like/", summary="帖子点赞")
async def snaps_like(id:Annotated[int, '帖子id'], session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    instance = await session.get(Snap, id)

    instance.like += 1

    await session.commit()
    await session.refresh(instance)

    return {"success": True,"like": instance.like}
