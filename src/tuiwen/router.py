from fastapi import APIRouter

from src.tuiwen.api.router import api_router_v2

api_router = APIRouter()

api_router.include_router(api_router_v2)

