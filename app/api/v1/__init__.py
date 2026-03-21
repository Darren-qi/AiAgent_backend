"""
API v1 路由初始化模块

导入并注册所有 v1 端点。
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    posts,
    agent,
    session,
    storage,
    social,
    notification,
    budget,
    health,
    websocket,
)

api_v1_router = APIRouter(prefix="/v1")

# 注册各个资源路由
api_v1_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_v1_router.include_router(users.router, prefix="/users", tags=["用户"])
api_v1_router.include_router(posts.router, prefix="/posts", tags=["文章"])
api_v1_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_v1_router.include_router(session.router, prefix="/session", tags=["Session"])
api_v1_router.include_router(storage.router, prefix="/storage", tags=["Storage"])
api_v1_router.include_router(social.router, prefix="/social", tags=["Social"])
api_v1_router.include_router(notification.router, prefix="/notification", tags=["通知"])
api_v1_router.include_router(budget.router, prefix="/budget", tags=["预算"])
api_v1_router.include_router(health.router, prefix="/health", tags=["健康检查"])
api_v1_router.include_router(websocket.router, prefix="/ws", tags=["WebSocket"])

__all__ = ["api_v1_router"]
