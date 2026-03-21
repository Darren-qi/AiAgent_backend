"""
API v1 路由
"""

from fastapi import APIRouter

from app.api.v1.endpoints import agent, session, storage, social, notification, budget, health

api_router = APIRouter()

api_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_router.include_router(session.router, prefix="/session", tags=["Session"])
api_router.include_router(storage.router, prefix="/storage", tags=["Storage"])
api_router.include_router(social.router, prefix="/social", tags=["Social"])
api_router.include_router(notification.router, prefix="/notification", tags=["Notification"])
api_router.include_router(budget.router, prefix="/budget", tags=["Budget"])
api_router.include_router(health.router, tags=["Health"])
