"""路由总装配。

api_router 是应用唯一对外的路由聚合点:
main.py 通过 app.include_router(api_router) 挂载,
内部将 api/router.py 的 api_router_v2(总前缀 /api/v2) 整体纳入。
"""
from fastapi import APIRouter

from src.tuiwen.api.router import api_router_v2

api_router = APIRouter()

api_router.include_router(api_router_v2)

