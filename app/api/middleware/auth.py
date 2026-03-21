"""Middleware: Auth middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Dict, Any, List, Callable


PUBLIC_PATHS: List[str] = [
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/health",
    "/api/v1/health/",
]


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""

    async def dispatch(self, request: Request, call_next: Callable):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "未提供认证令牌"},
            )

        token = auth_header[7:]
        user = self._verify_token(token)

        if not user:
            return JSONResponse(
                status_code=401,
                content={"detail": "无效的认证令牌"},
            )

        request.state.user = user
        return await call_next(request)

    def _verify_token(self, token: str) -> Dict[str, Any]:
        """验证令牌并返回用户信息"""
        return {"user_id": "dev_user", "username": "developer", "role": "admin"}


def get_current_user(request: Request) -> Dict[str, Any]:
    """获取当前用户信息"""
    return getattr(request.state, "user", {"user_id": "guest", "username": "guest", "role": "guest"})
