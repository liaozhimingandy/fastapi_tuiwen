from typing import Annotated

from fastapi import APIRouter, Request, Depends

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_feedback_dao
from src.tuiwen.more.models import FeedbackResponse, FeedbackCreate, Feedback, FeedbackStatus
from src.tuiwen.service.feedback import FeedbackService

router_public = APIRouter(tags=[Tag.more])


@router_public.post("/v2/feedbacks/", response_model=FeedbackResponse, status_code=201, summary="提交用户反馈")
async def submit_feedback(
        payload: Annotated[FeedbackCreate, "反馈内容"],
        request: Annotated[Request, "请求对象"],
        svc: FeedbackService = Depends(get_feedback_dao)
):
    """
    # status枚举值
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | CLOSED | 0 | 已关闭 |
    | PENDING | 1 | 待处理 |
    | PROCESSING | 2 | 处理中 |
    | DONE | 3 | 已处理完成 |

    # feedback_type枚举值
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | SUGGEST | 1 | 建议 |
    | BUG | 2 | bug |
    | COMPLAINT | 3 | 投诉 |
    | OTHER | 0 | 其它 |

    # level枚举值
    | 枚举常量 | 值 | 中文说明 |
    |---|---|---|
    | LOW | 1 | 低 |
    | NORMAL | 2 | 中 |
    | HIGH | 3 | 高 |

    """
    instance = Feedback(
        **payload.model_dump(),
        account_id=request.state.account_id if request.state else None,
        user_agent=request.headers.get("user-agent"),
        from_ip=request.client.host if request.client else None,
        status=FeedbackStatus.PENDING
    )
    item = await svc.create_feedback(instance)
    return item