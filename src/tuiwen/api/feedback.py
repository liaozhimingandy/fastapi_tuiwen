"""
用户反馈 API 路由层(公开接口, 无需登录)

职责:
    1. 接收匿名/已登录用户提交的反馈
    2. 补充服务端上下文(账户、User-Agent、来源 IP、初始状态)后落库

分层位置:
    API → FeedbackService → FeedbackDAO → PostgreSQL
"""
from typing import Annotated

from fastapi import APIRouter, Request, Depends, HTTPException

from src.tuiwen.core import Tag
from src.tuiwen.dependencies import get_feedback_service
from src.tuiwen.model.feedback import FeedbackResponse, FeedbackCreate, Feedback, FeedbackStatus
from src.tuiwen.service.feedback import FeedbackService

# 反馈接口不要求登录: 未登录用户同样可以提交
router_public = APIRouter(prefix='/feedbacks', tags=[Tag.more])


@router_public.post("/", response_model=FeedbackResponse, status_code=201, summary="提交用户反馈")
async def submit_feedback(
        payload: Annotated[FeedbackCreate, "反馈内容"],
        request: Annotated[Request, "请求对象"],
        svc: FeedbackService = Depends(get_feedback_service)
):
    """
    提交一条用户反馈

    入参 payload 仅包含客户端可填写的部分(类型/级别/内容/联系方式),
    其余字段在服务端补全, 避免被客户端篡改。

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
    # 补全服务端字段: 账户ID(匿名时为空)、UA、来源IP、初始状态固定为待处理
    # 反馈接口是公开路由, 没有认证依赖写入 account_id, 必须用 getattr 兜底,
    # 直接写 request.state.account_id 在匿名提交时会抛 AttributeError
    instance = Feedback(
        **payload.model_dump(),
        account_id=getattr(request.state, "account_id", None),
        user_agent=request.headers.get("user-agent"),
        from_ip=request.client.host if request.client else None,
        status=FeedbackStatus.PENDING
    )
    try:
        return await svc.create_feedback(instance)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
