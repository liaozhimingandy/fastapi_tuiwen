import uuid
from typing import Annotated

from fastapi import APIRouter, Body, status, Depends, Request, Path, Query

from dependencies import get_comment_service
from models import PageResponse
from src.tuiwen.service.comment import CommentService
from src.tuiwen.core import Tag
from src.tuiwen.post.models import Comment, CommentInput

router_comment = APIRouter(prefix="/v2/comments", tags=[Tag.comment])

@router_comment.post('/', summary="新增评论", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(comment: Annotated[CommentInput, Body(..., description="评论信息")],
                         svc: CommentService = Depends(get_comment_service)):
    comment_data = comment.model_dump(exclude={"id", "create_at", "comment_id"})
    instance = Comment(**comment_data, comment_id=str(uuid.uuid7()))

    return await svc.create(instance)


@router_comment.delete('/{comment_id}/', summary='删除指定的评论', status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: Annotated[uuid.UUID, '评论ID'], request: Annotated[Request, "请求对象"],
                         svc: CommentService = Depends(get_comment_service)):

    return await svc.delete(comment_id=comment_id, account_id=request.state.account_id)



@router_comment.get('/{obj_type}/{obj_id}/', summary="查询指定帖子的评论", response_model=PageResponse[Comment],
                    response_model_include={'items', 'total'})
async def get_comments(
        obj_id: Annotated[str, "评论ID"] = Path(...),
        obj_type: Annotated[int, "枚举类型"] = Path(..., description="目标对象类型枚举值", ge=1, le=1),
        limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
        cursor: Annotated[uuid.UUID | None, "最早的那个id"] = Query(None),
        svc: CommentService = Depends(get_comment_service)):

    dataset = await svc.get(obj_id=obj_id, obj_type=obj_type, limit=limit, offset=cursor)

    return PageResponse(items=dataset, total=len(dataset))