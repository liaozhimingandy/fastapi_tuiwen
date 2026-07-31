import hashlib
import uuid
import os
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete, update, exists, or_
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request, Query, Path, Body, status

from src.tuiwen.core import get_settings, Settings, Tag, add_instance
from src.tuiwen.dependencies import get_session
from src.tuiwen.post.models import Post, PostCreate, Comment, Like, Image as TWImage, ImageBase, PostRightStatusUpdate, \
    CommentInput, LikeInput, Follow, FollowCountModel, LikeCountModel
from src.tuiwen.models import PageResponse
from src.tuiwen.utils import allowed_file

router_post = APIRouter(prefix="/posts", tags=[Tag.post])


@router_post.post("/", summary="发布帖子", response_model=Post, status_code=status.HTTP_201_CREATED)
async def create_post(post: Annotated[PostCreate, Body(..., description="帖子信息")],
                      request: Annotated[Request, "请求对象"],
                      session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    post_data = post.model_dump(exclude={"from_ip", "post_id"})

    # 提取ip地址
    client_ip = None
    if request.client:
        client_ip = request.client.host

    instance = Post(**post_data, from_ip=client_ip, post_id=str(uuid.uuid7()))
    instance = await add_instance(session, instance)

    return instance


@router_post.get("/latest/", summary="返回最近十条帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts_latest(request: Annotated[Request, "请求对象"],
                           session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = select(Post).where(
        or_(Post.right_status == Post.RightStatusEnum.PUBLIC, Post.account_id == request.state.account_id))
    dataset = (await session.exec(statement)).all()

    return PageResponse(items=dataset, total=len(dataset))


@router_post.get("/accounts/{account_id}/", summary="返回指定用户的所有帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_account_posts(account_id: Annotated[str, Path(..., description="用户ID")],
                            request: Annotated[Request, "请求对象"],
                            limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100,
                                                                            description="每页数量(1-100)"),
                            cursor: Annotated[UUID | None, "数据最旧的ID"] = Query(None),
                            session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)
                            ):
    statement = select(Post).where(Post.account_id == account_id)
    # 如果和认证用户一致,则返回所有，否则查公开帖子
    if not account_id == request.state.account_id:
        statement = statement.where(
            Post.right_status == Post.RightStatusEnum.PUBLIC
        )

    # 仅当有游标时添加时间条件
    if cursor:
        statement = statement.where(Post.post_id < cursor)

    # 按创建时间倒序 + 限制数量
    statement = statement.order_by(-Post.id).limit(limit)

    dataset = (await session.exec(statement)).all()
    total = len(dataset)  # 实际返回数量（分页场景建议用count查询，此处简化）

    return PageResponse(items=dataset, total=total)


@router_post.get("/", summary="返回帖子", response_model=PageResponse[Post],
                 response_model_include={'items', 'total'})
async def get_posts(request: Annotated[Request, "请求对象"],
                    limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
                    cursor: Annotated[UUID | None, "数据最旧的那个post_id"] = Query(None),
                    session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)
                    ):
    # 构建查询（保持UTC时间比较）
    statement = select(Post).where(
        or_(Post.right_status == Post.RightStatusEnum.PUBLIC, Post.account_id == request.state.account_id))

    if cursor:
        statement = statement.where(Post.post_id < cursor)

    # 按创建时间倒序 + 限制数量
    statement = statement.order_by(-Post.id).limit(limit)

    dataset = (await session.exec(statement)).all()
    total = len(dataset)  # 实际返回数量（分页场景建议用count查询，此处简化）

    return PageResponse(items=dataset, total=total)


@router_post.put('/{post_id}/right/', summary="更新帖子的公开状态", status_code=status.HTTP_205_RESET_CONTENT)
async def update_post_right(post_id: Annotated[UUID, "帖子ID"],
                            post_right: Annotated[PostRightStatusUpdate, Body(..., description="权限信息")],
                            request: Annotated[Request, "请求对象"],
                            session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = update(Post).where(Post.post_id == post_id, Post.account_id == request.state.account_id).values(
        right_status=post_right.right_status)
    await session.exec(statement)
    await session.commit()


@router_post.delete("/{post_id}/", summary="删除指定的帖子", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(request: Annotated[Request, "请求对象"],
                      post_id: Annotated[UUID, Path(..., description="帖子ID")],
                      session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = delete(Post).where(Post.post_id == post_id, Post.account_id == request.state.account_id)

    await session.exec(statement)
    await session.commit()


########################################################################################################################
router_comment = APIRouter(prefix="/comments", tags=[Tag.comment])


@router_comment.post('/', summary="新增评论", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(comment: Annotated[CommentInput, Body(..., description="评论信息")],
                         session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    comment_data = comment.model_dump(exclude={"id", "gmt_created", "comment_id"})
    instance = Comment(**comment_data, comment_id=str(uuid.uuid7()))

    instance = await add_instance(session, instance)

    return instance


@router_comment.delete('/{comment_id}/', summary='删除指定的评论', status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: Annotated[UUID, '评论ID'], request: Annotated[Request, "请求对象"],
                         session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = delete(Comment).where(Comment.comment_id == comment_id, Comment.account_id == request.state.account_id)

    await session.exec(statement)
    await session.commit()


@router_comment.get('/{obj_type}/{obj_id}/', summary="查询指定帖子的评论", response_model=PageResponse[Comment],
                    response_model_include={'items', 'total'})
async def get_comments(
        obj_id: Annotated[str, "评论ID"] = Path(...),
        obj_type: Annotated[int, "枚举类型"] = Path(..., description="目标对象类型枚举值", ge=1, le=1),
        limit: Annotated[int, "返回多少条记录"] = Query(10, ge=1, le=100, description="每页数量(1-100)"),
        cursor: Annotated[UUID | None, "最早的那个id"] = Query(None),
        session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = select(Comment).where(Comment.obj_id == obj_id, Comment.obj_type == Comment.ObjTypeEnum(obj_type))
    if cursor:
        statement = statement.where(Comment.comment_id < cursor)

    statement = statement.order_by(-Comment.id).limit(limit)
    dataset = (await (session.exec(statement))).all()

    return PageResponse(items=dataset, total=len(dataset))


########################################################################################################################
router_like = APIRouter(prefix="/likes", tags=[Tag.like])


@router_like.post('/', summary="点赞", response_model=Like, status_code=status.HTTP_201_CREATED)
async def create_like(like: Annotated[LikeInput, "赞的输入对象"],
                      session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    like_data = like.model_dump(exclude={"id", "gmt_created"})
    instance = Like(**like_data)

    instance = await add_instance(session, instance)

    return instance


@router_like.delete('/{obj_id}/', summary='取消赞', status_code=status.HTTP_204_NO_CONTENT)
async def delete_like(obj_id: Annotated[uuid.UUID, "对象ID"], request: Annotated[Request, "请求对象"],
                      session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = delete(Like).where(Like.obj_id == obj_id, Like.account_id == request.state.account_id,
                                   Like.obj_type == Like.ObjTypeEnum.POST)
    await session.exec(statement)
    await session.commit()


@router_like.get('/{obj_id}/count/', summary="获取指定帖子的点赞数", response_model=LikeCountModel)
async def get_like_count(obj_id: Annotated[str, "对象id"], request: Annotated[Request, "请求对象"],
                         session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)) -> LikeCountModel:
    statement = select(Like.id).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST)
    statement_sub = select(Like).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST,
                                       Like.account_id == request.state.account_id)
    statement2 = select(exists().select_from(statement_sub))
    like_count = len((await session.exec(statement)).all())
    is_liked = (await session.exec(statement2)).first()

    return LikeCountModel(count=like_count, is_liked=is_liked)


########################################################################################################################
router_upload = APIRouter(prefix="/upload", tags=[Tag.upload])


@router_upload.post('/image/', summary="图片上传", response_model=ImageBase, status_code=status.HTTP_201_CREATED)
async def upload_image(file: Annotated[UploadFile, "图片文件"],
                       session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session),
                       settings: Annotated[Settings, "全局的设置对象"] = Depends(get_settings)):
    # 检查文件类型
    if not allowed_file(file, file_type=settings.ALLOWED_IMAGE_FORMATS.split(",")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"invalid file type. Only {settings.ALLOWED_IMAGE_FORMATS} images are allowed.")

    contents = await file.read()  # 读取文件内容

    # 计算文件的MD5值
    md5 = hashlib.md5()
    md5.update(contents)
    image_md5 = md5.hexdigest()

    # 判断文件是否存在
    statement = select(TWImage).where(TWImage.image_md5 == image_md5)
    instance = (await session.exec(statement)).first()

    if not instance:
        # 保存到文件
        upload_dir = "static/medias/images"
        # 判断文件夹是否存在,不存在则新建
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        file_path = f"{upload_dir}/{str(uuid.uuid4())}{os.path.splitext(file.filename)[1]}"
        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        # 保存引用到数据库
        instance = TWImage(image_url=file_path, image_name=file.filename, image_md5=image_md5)
        instance = await add_instance(session, instance)

    return ImageBase(image_url=f"{settings.STATIC_URL}/{instance.image_url}", image_md5=image_md5)


########################################################################################################################
# follow

router_follow = APIRouter(prefix="/follows", tags=["follow"])


@router_follow.post('/', summary="关注", response_model=Follow, status_code=status.HTTP_201_CREATED)
async def follow(follow: Annotated[Follow, Body(..., description="关注信息")],
                 session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)) -> Follow:
    follow_data = follow.model_dump(exclude={"id", "gmt_created"})
    instance = Follow(**follow_data)

    instance = await add_instance(session, instance)
    return instance


@router_follow.delete('/{follower_id}/{followee_id}/', summary="取消关注", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow(follower_id: Annotated[str, "追随者ID"], followee_id: Annotated[str, "被关注者ID"],
                        session: Annotated[AsyncSession, "会话依赖"] = Depends(get_session)):
    statement = delete(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    await session.exec(statement)
    await session.commit()


@router_follow.get('/{account_id}/count/', summary="获取指定帐户的关注和正在关注数量及获赞数量",
                   response_model=FollowCountModel)
async def get_follow_info_by_id(account_id: Annotated[str, "账户ID"], request: Annotated[Request, "请求对象"],
                                session: Annotated[AsyncSession, "会话依赖"] = Depends(
                                    get_session)) -> FollowCountModel:
    """
    获取指定帐户的关注和正在关注数量及获赞数量

    - **account_id**: 平台账号唯一标识
    """
    stmt = select(Follow).where(Follow.followee_id == account_id)  # 粉丝数
    stmt2 = select(Follow).where(Follow.follower_id == account_id)  # 正在关注

    stmt_sub = select(Follow.id).where(Follow.followee_id == account_id,
                                       Follow.follower_id == request.state.account_id)  # 是否在关注
    stmt_following = select(exists().select_from(stmt_sub))
    # 粉丝数
    follower_count = len((await session.exec(stmt)).all())
    # 正在关注数
    followee_count = len((await session.exec(stmt2)).all())
    # 是否正在关注
    is_following = (await session.exec(stmt_following)).first()
    # 获赞数量
    like_count = 0

    return FollowCountModel(follower_count=follower_count, followee_count=followee_count, is_following=is_following,
                            like_count=like_count)
