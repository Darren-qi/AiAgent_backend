"""API v1 endpoints"""
from app.api.v1.endpoints.agent import router as agent_router
from app.api.v1.endpoints.session import router as session_router
from app.api.v1.endpoints.storage import router as storage_router
from app.api.v1.endpoints.social import router as social_router
from app.api.v1.endpoints.notification import router as notification_router
from app.api.v1.endpoints.budget import router as budget_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.websocket import router as websocket_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.posts import router as posts_router
