"""
API 路由总装配入口

职责:
    1. 汇总各业务模块的子路由(账号/评论/帖子/关注/通知/点赞/上传/反馈/快照)
    2. 按「是否需要登录」划成两个分组:
        - router_auth  : 挂载 check_authentication 依赖, 组内请求必须携带合法 access_token
        - router_public: 不挂认证依赖, 允许匿名访问
    3. 统一挂到 /api/v2 前缀对外暴露 (main.py 中 app.include_router(api_router))

分层位置:
    main.py → api_router → router_auth / router_public → 各业务模块 router → Service → DAO
"""
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

# 全部业务接口的统一前缀, 最终对外路径形如 /api/v2/posts/
api_router = APIRouter(prefix="/api/v2")
# 公开分组: 无认证依赖, 提供注册/登录/验证码/公开帖子等匿名能力
router_public = APIRouter(dependencies=[])
# 受保护分组: 组内任一接口被访问前, 都会先执行 check_authentication 校验令牌
router_auth = APIRouter(dependencies=[Depends(check_authentication)])

# -------------------- 需登录认证的模块 --------------------
router_auth.include_router(router_oauth)    # 令牌刷新、鉴权自测
router_auth.include_router(router_comment)  # 评论
router_auth.include_router(router_post)     # 帖子
router_auth.include_router(router_follow)   # 关注
router_auth.include_router(router_notice)   # 通知
router_auth.include_router(router_like)     # 点赞
router_auth.include_router(router_upload)   # 文件上传

# -------------------- 免登录(公开)的模块 --------------------
router_public.include_router(account_router_public)   # 注册/登录/找回密码/公开账户信息
router_public.include_router(feedback_router_public)  # 用户反馈
router_public.include_router(snap_router_public)      # 天亮即焚
router_public.include_router(post_router_public)      # 公开帖子

# 两个分组统一挂到 /api/v2 之下
api_router.include_router(router_auth)
api_router.include_router(router_public)
