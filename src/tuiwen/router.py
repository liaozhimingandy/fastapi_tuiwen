from fastapi import APIRouter, Depends

from src.tuiwen.dependencies import check_authentication
from src.tuiwen.account.router import router_oauth, router_account, router_public as router_public_account
from src.tuiwen.post.router import router_post, router_like, router_upload, router_comment, router_follow
from src.tuiwen.notice.router import router_notice

api_router = APIRouter()
router_public = APIRouter(dependencies=[])
router_auth = APIRouter(dependencies=[Depends(check_authentication)])

# 路由分组

router_auth.include_router(router_oauth)
# app.include_router(router_app)
router_auth.include_router(router_account)
router_auth.include_router(router_post)
router_auth.include_router(router_like)
router_auth.include_router(router_comment)
router_auth.include_router(router_upload)
router_auth.include_router(router_follow)
router_auth.include_router(router_notice)

router_public.include_router(router_public_account)

################################################################################
api_router.include_router(router_auth)
api_router.include_router(router_public)
