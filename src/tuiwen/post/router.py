import hashlib
import uuid
import os
from typing import Annotated

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from typing_extensions import Doc

from sqlmodel import select

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request

from src.tuiwen.config import Settings, settings
from src.tuiwen.dependencies import check_authentication, get_session
from src.tuiwen.post.models import Post, PostCreate, Comment, Like, Image as TWImage, ImageBase
from src.tuiwen.utils.utils import allowed_file

router_post = APIRouter(prefix="/posts", tags=["post"], dependencies=[Depends(check_authentication)])


@router_post.post("/", summary="发布帖子", response_model=Post)
async def create_post(post: PostCreate, request: Request, session: AsyncSession = Depends(get_session)):
    post_data = Post.model_dump(post, exclude={"from_ip"})
    instance = Post(**post_data)
    # 提取ip地址
    instance.from_ip = request.client.host

    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请勿重复提交")

    return instance


@router_post.delete("/{post_id}/", summary="删除指定的帖子")
async def delete_post(post_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Post).where(Post.post_id == post_id, Post.account_id == request.state.account_id)
    results = await session.exec(statement)
    instance = results.first()

    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="post not found")

    await session.delete(instance)
    await session.commit()

    return {"message": "success"}

########################################################################################################################
router_comment = APIRouter(prefix="/comments", tags=["comment"], dependencies=[Depends(check_authentication)])


@router_comment.post('/', summary="新增评论", response_model=Comment)
async def create_comment(comment: Comment, session: AsyncSession = Depends(get_session)):
    comment_data = Post.model_dump(comment, exclude={"id", "gmt_created"})
    instance = Comment(**comment_data)

    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请勿重复提交")

    return instance


@router_comment.delete('/{comment_id}/', summary='删除指定的评论', dependencies=[])
async def delete_comment(comment_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Comment).where(Comment.comment_id == comment_id, Comment.account_id == request.state.account_id)
    results = await session.exec(statement)
    instance = results.first()

    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comment not found")

    await session.delete(instance)
    await session.commit()

    return {"message": "success"}

########################################################################################################################
router_like = APIRouter(prefix="/likes", tags=["like"], dependencies=[Depends(check_authentication)])


@router_like.post('/', summary="点赞", response_model=Like)
async def create_like(like: Like, session: AsyncSession = Depends(get_session)):
    like_data = Like.model_dump(like, exclude={"id", "gmt_created"})
    instance = Like(**like_data)
    try:
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请勿重复提交")

    return instance

@router_like.delete('/{post_id}/', summary='取消赞', dependencies=[])
async def delete_like(post_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Like).where(Like.post_id == post_id, Like.account_id == request.state.account_id)
    results = await session.exec(statement)
    instance = results.first()

    if not instance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="like not found")

    await session.delete(instance)
    await session.commit()

    return {"message": "success"}

########################################################################################################################
router_upload = APIRouter(prefix="/upload", tags=["upload"], dependencies=[Depends(check_authentication)])


@router_upload.post('/image/', summary="图片上传", response_model=ImageBase)
async def upload_image(file: Annotated[UploadFile, Doc("图片文件")], settings: Settings=settings,
                       session: AsyncSession = Depends(get_session)):
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
    dataset = await session.exec(statement)
    instance = dataset.first()

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
        try:
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
        except IntegrityError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return ImageBase(image_url=f"{settings.STATIC_URL}/{instance.image_url}", image_md5=image_md5)
