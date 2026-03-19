"""
API v1 路由初始化模块

导入并注册所有 v1 端点。
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, users, posts

api_v1_router = APIRouter(prefix="/v1")

# 注册各个资源路由
api_v1_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_v1_router.include_router(users.router, prefix="/users", tags=["用户"])
api_v1_router.include_router(posts.router, prefix="/posts", tags=["文章"])

__all__ = ["api_v1_router"]
