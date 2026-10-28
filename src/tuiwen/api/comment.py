"""
评论 API 路由层

职责:
    1. 只做 HTTP 协议转换: 参数解析/校验 → 调用 Service → 返回响应模型
    2. 不写业务逻辑, 不直接操作数据库

接口清单:
    POST   /api/v2/comments/                      新增评论
    DELETE /api/v2/comments/{comment_id}/         删除评论(仅本人)
    GET    /api/v2/comments/{target_type}/{target_id}/  分页查询某对象的评论

分层位置:
    API → CommentService → CommentDAO → PostgreSQL
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, status, Depends, Request, Path, Query

from src.tuiwen.dependencies import get_comment_service
from src.tuiwen.models import PageResponse
from src.tuiwen.service.comment import CommentService
from src.tuiwen.core import Tag
from src.tuiwen.model.comment import Comment, CommentCreate

router_comment = APIRouter(prefix="/comments", tags=[Tag.comment])


@router_comment.post('/', summary="新增评论", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(comment: Annotated[CommentCreate, Body(..., description="评论信息")],
                         request: Annotated[Request, "请求对象"],
                         svc: CommentService = Depends(get_comment_service)):
    """
    新增一条评论

    Args:
        comment: 评论入参, 包含目标对象(target_id/target_type)、内容与可选的父评论
        request: 请求对象, request.state.account_id 由认证依赖写入
        svc: 评论业务服务(依赖注入), 内部持有 CommentDAO

    Returns:
        Comment: 落库后的评论实体(含数据库生成的 id / comment_id)
    """
    # 评论者取自令牌, 不接受客户端传入; 是否一级评论由 parent_id 推导
    instance = Comment(
        **comment.model_dump(),
        is_root=comment.parent_id is None,
        account_id=request.state.account_id,
        # comment_id 使用 uuid7, 时间有序, 便于按主键做游标分页
        id=uuid.uuid7(),
    )

    result = await svc.create(instance)
    # 事务出口: DAO 只 flush, 由 API 层统一提交
    await svc.dao.commit()
    return result


@router_comment.delete('/{comment_id}/', summary='删除指定的评论', status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: Annotated[uuid.UUID, '评论ID'], request: Annotated[Request, "请求对象"],
                         svc: CommentService = Depends(get_comment_service)):
    """
    删除指定评论

    Args:
        comment_id: 待删除的评论 ID
        request: 请求对象; request.state.account_id 由认证依赖写入, 用于越权校验
        svc: 评论业务服务

    Returns:
        bool: 是否真正删除了记录(204 无响应体, 调用方以状态码判断)
    """
    # 以 comment_id + account_id 双条件删除, 保证只能删除自己发表的评论
    affected = await svc.delete(comment_id=comment_id, account_id=request.state.account_id)
    # 事务出口: DAO 只执行 DELETE, 由 API 层统一提交
    await svc.dao.commit()
    return affected


@router_comment.get('/{target_type}/{target_id}/', summary="查询指定帖子的评论", response_model=PageResponse[Comment],
                    response_model_include={'items', 'total'})
async def get_comments(
        target_id: Annotated[uuid.UUID, "评论对象ID"] = Path(...),
        target_type: Annotated[int, "枚举类型"] = Path(..., description="目标对象类型枚举值", ge=1, le=1),
        limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
        cursor: Annotated[uuid.UUID | None, "最早的那个id"] = Query(None),
        svc: CommentService = Depends(get_comment_service)):
    """
    分页查询某个目标对象(帖子等)下的评论列表

    Args:
        target_id: 目标对象 ID, 如帖子 post_id
        target_type: 目标对象类型枚举值, 当前仅允许 1(帖子)
        limit: 每页数量, 取值 1~100
        cursor: 游标(上一页最旧一条的 ID), 用于向前翻页; 为空表示查第一页
        svc: 评论业务服务

    Returns:
        PageResponse[Comment]: 评论列表与总数
    """
    # cursor 是游标(上一页最旧一条的 comment_id), 不是 offset, 由 Service 转交 DAO 做游标分页
    result = await svc.get(target_id=target_id, target_type=target_type, limit=limit, cursor=cursor)

    return PageResponse(items=result.items, total=result.total)
