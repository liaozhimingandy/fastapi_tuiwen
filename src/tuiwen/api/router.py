from fastapi import APIRouter, Depends

from src.tuiwen.dependencies import check_authentication
from src.tuiwen.api.account import router_oauth, router_public as account_router_public
from src.tuiwen.api.comment import router_comment
from src.tuiwen.api.feedback import router_public as feedback_router_public
from src.tuiwen.api.follow import router_follow
from src.tuiwen.api.notice import router_notice
from src.tuiwen.api.like import router_like
from src.tuiwen.api.post import router_post, router_public as post_router_public
from src.tuiwen.api.snap import router_public as snap_router_public
from src.tuiwen.api.upload import router_upload

api_router = APIRouter(prefix="/api/v2")
router_public = APIRouter(dependencies=[])
router_auth = APIRouter(dependencies=[Depends(check_authentication)])

router_auth.include_router(router_oauth)
router_auth.include_router(router_comment)
router_auth.include_router(router_post)
router_auth.include_router(router_follow)
router_auth.include_router(router_notice)
router_auth.include_router(router_like)
router_auth.include_router(router_upload)

router_public.include_router(account_router_public)
router_public.include_router(feedback_router_public)
router_public.include_router(snap_router_public)
router_public.include_router(post_router_public)

api_router.include_router(router_auth)
api_router.include_router(router_public)


