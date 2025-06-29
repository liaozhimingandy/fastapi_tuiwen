import hashlib
import uuid
import os
from typing import Annotated, Any

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from typing_extensions import Doc
from sqlmodel import select, delete, update, exists
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request

from src.tuiwen.core import get_settings, Settings
from src.tuiwen.core.database import add_instance
from src.tuiwen.dependencies import check_authentication, get_session
from src.tuiwen.models import ResponsePublic
from src.tuiwen.post.models import Post, PostCreate, Comment, Like, Image as TWImage, ImageBase, PostRightStatusUpdate, \
    CommentInput, LikeInput, Follow, FollowCountModel, LikeCountModel
from src.tuiwen.utils.utils import allowed_file, convert_to_cst_time

router_post = APIRouter(prefix="/posts", tags=["post"], dependencies=[Depends(check_authentication)])


@router_post.post("/", summary="发布帖子", response_model=Post, status_code=status.HTTP_201_CREATED)
async def create_post(post: PostCreate, request: Request, session: AsyncSession = Depends(get_session)):
    post_data = Post.model_dump(post, exclude={"from_ip"})
    instance = Post(**post_data)
    # 提取ip地址
    instance.from_ip = request.client.host

    instance = await add_instance(session, instance)

    # 处理时区问题: todo: 寻找更优雅的实现方式
    instance.gmt_created = convert_to_cst_time(instance.gmt_created)
    return instance

@router_post.get("/lasted/", summary="返回最近十条帖子", response_model=list[Post])
async def get_posts_lasted(session: AsyncSession = Depends(get_session)):
    statement = select(Post).where(Post.right_status == Post.RightStatusEnum.PUBLIC).order_by(-Post.id).limit(10)
    ds = (await (session.exec(statement))).all()
    for post in ds:
        post.gmt_created = convert_to_cst_time(post.gmt_created)
    return ds

@router_post.put('/{post_id}/right/', summary="更新帖子的公开状态", status_code=status.HTTP_205_RESET_CONTENT)
async def update_post_right(post_id: str, post_right: PostRightStatusUpdate, request: Request, session: AsyncSession = Depends(get_session)):
    statement = update(Post).where(Post.post_id == post_id, Post.account_id == request.state.account_id).values(right_status=post_right.right_status)
    await session.exec(statement)
    await session.commit()

@router_post.delete("/{post_id}/", summary="删除指定的帖子", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = delete(Post).where(Post.post_id == post_id, Post.account_id == request.state.account_id)

    await session.exec(statement)
    await session.commit()


########################################################################################################################
router_comment = APIRouter(prefix="/comments", tags=["comment"], dependencies=[Depends(check_authentication)])


@router_comment.post('/', summary="新增评论", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(comment: CommentInput, session: AsyncSession = Depends(get_session)):
    comment_data = CommentInput.model_dump(comment, exclude={"id", "gmt_created"})
    instance = Comment(**comment_data)

    instance = await add_instance(session, instance)

    instance.gmt_created = convert_to_cst_time(instance.gmt_created)
    return instance


@router_comment.delete('/{comment_id}/', summary='删除指定的评论', status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = delete(Comment).where(Comment.comment_id == comment_id, Comment.account_id == request.state.account_id)

    await session.exec(statement)
    await session.commit()


@router_comment.get('/{obj_type}/{obj_id}/', summary="查询指定帖子的评论", response_model=list[Comment])
async def get_comments(obj_id: str, obj_type: int = Comment.ObjTypeEnum.POST, session: AsyncSession = Depends(get_session)):
    stmt = select(Comment).where(Comment.obj_id == obj_id, Comment.obj_type ==  Comment.ObjTypeEnum(obj_type))
    ds = (await (session.exec(stmt))).all()
    for post in ds:
        post.gmt_created = convert_to_cst_time(post.gmt_created)
    return ds

########################################################################################################################
router_like = APIRouter(prefix="/likes", tags=["like"], dependencies=[Depends(check_authentication)])


@router_like.post('/', summary="点赞", response_model=Like, status_code=status.HTTP_201_CREATED)
async def create_like(like: LikeInput, session: AsyncSession = Depends(get_session)):
    like_data = LikeInput.model_dump(like, exclude={"id", "gmt_created"})
    instance = Like(**like_data)

    instance = await add_instance(session, instance)

    instance.gmt_created = convert_to_cst_time(instance.gmt_created)
    return instance

@router_like.delete('/{obj_id}/', summary='取消赞', status_code=status.HTTP_204_NO_CONTENT)
async def delete_like(obj_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = delete(Like).where(Like.obj_id == obj_id, Like.account_id == request.state.account_id,
                                   Like.obj_type==Like.ObjTypeEnum.POST)
    await session.exec(statement)
    await session.commit()


@router_like.get('/{obj_id}/count/', summary="获取指定帖子的点赞数", response_model=LikeCountModel)
async def get_like_count(obj_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> LikeCountModel:
    stmt = select(Like.id).where(Like.obj_id == obj_id,  Like.obj_type == Like.ObjTypeEnum.POST)
    stmt_sub  = select(Like).where(Like.obj_id == obj_id, Like.obj_type == Like.ObjTypeEnum.POST, Like.account_id == request.state.account_id)
    stmt2 = select(exists().select_from(stmt_sub))
    like_count = len((await session.exec(stmt)).all())
    is_liked = (await session.exec(stmt2)).first()

    return LikeCountModel(count=like_count, is_liked=is_liked)

########################################################################################################################
router_upload = APIRouter(prefix="/upload", tags=["upload"], dependencies=[Depends(check_authentication)])


@router_upload.post('/image/', summary="图片上传", response_model=ImageBase, status_code=status.HTTP_201_CREATED)
async def upload_image(file: Annotated[UploadFile, Doc("图片文件")], session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    # 检查文件类型
    if not allowed_file(file, file_type=settings.ALLOWED_IMAGE_FORMATS.split(",")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid file type. Only {settings.ALLOWED_IMAGE_FORMATS} images are allowed.")

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

router_follow = APIRouter(prefix="/follows", tags=["follow"], dependencies=[Depends(check_authentication)])

@router_follow.post('/', summary="关注", response_model=Follow, status_code=status.HTTP_201_CREATED)
async def follow(follow: Follow, session: AsyncSession = Depends(get_session)):
    follow_data = Follow.model_dump(follow, exclude={"id", "gmt_created"})
    instance = Follow(**follow_data)

    instance = await add_instance(session, instance)
    return instance


@router_follow.delete('/{follower_id}/{followee_id}/', summary="取消关注", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow(follower_id: str, followee_id:str, session: AsyncSession = Depends(get_session)):
    statement = delete(Follow).where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
    await session.exec(statement)
    await session.commit()


@router_follow.get('/{account_id}/count/', summary="获取指定帐户的关注和正在关注数量及获赞数量",
                   response_model=FollowCountModel)
async def get_follow_info_by_id(account_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> FollowCountModel:
    """
    获取指定帐户的关注和正在关注数量及获赞数量

    - **account_id**: 平台账号唯一标识
    """
    stmt = select(Follow).where(Follow.followee_id == account_id)  # 粉丝数
    stmt2 = select(Follow).where(Follow.follower_id == account_id) # 正在关注

    stmt_sub = select(Follow.id).where(Follow.followee_id == account_id, Follow.follower_id == request.state.account_id) # 是否在关注
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
