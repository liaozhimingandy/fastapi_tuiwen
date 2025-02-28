from fastapi import APIRouter
router_public = APIRouter()

from src.tuiwen.account.router import router_oauth, router_account
from src.tuiwen.post.router import router_post, router_like, router_upload, router_comment, router_follow

api_router = APIRouter()


api_router.include_router(router_oauth)
api_router.include_router(router_public)
# app.include_router(router_app)
api_router.include_router(router_account)
api_router.include_router(router_post)
api_router.include_router(router_like)
api_router.include_router(router_comment)
api_router.include_router(router_upload)
api_router.include_router(router_follow)