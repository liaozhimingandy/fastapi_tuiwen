from typing import Annotated

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.tuiwen.core import Tag, add_instance
from src.tuiwen.dependencies import get_session
from .models import Feedback, FeedbackStatus, FeedbackCreate, FeedbackResponse

router_public = APIRouter(prefix="/feebacks", tags=[Tag.more])

@router_public.post("/", response_model=FeedbackResponse, description="提交用户反馈")
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
