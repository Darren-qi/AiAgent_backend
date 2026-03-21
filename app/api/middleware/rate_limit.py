"""Middleware: Rate limit middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Dict, Callable
import time
from collections import defaultdict


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于滑动窗口算法的 IP 限流中间件"""

    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.window_minute: Dict[str, list] = defaultdict(list)
        self.window_hour: Dict[str, list] = defaultdict(list)

    def _clean_old_requests(self, client_ip: str) -> None:
        """清理过期的请求记录"""
        now = time.time()
        minute_threshold = now - 60
        hour_threshold = now - 3600
        self.window_minute[client_ip] = [
            t for t in self.window_minute[client_ip] if t > minute_threshold
        ]
        self.window_hour[client_ip] = [
            t for t in self.window_hour[client_ip] if t > hour_threshold
        ]

    def _check_rate_limit(self, client_ip: str) -> tuple[bool, str]:
        """检查速率限制"""
        now = time.time()
        self._clean_old_requests(client_ip)

        if len(self.window_minute[client_ip]) >= self.requests_per_minute:
            return False, "请求过于频繁，请稍后再试"
        if len(self.window_hour[client_ip]) >= self.requests_per_hour:
            return False, "请求次数超限，请稍后再试"

        self.window_minute[client_ip].append(now)
        self.window_hour[client_ip].append(now)
        return True, ""

    async def dispatch(self, request: Request, call_next: Callable):
        client_ip = request.client.host if request.client else "unknown"

        allowed, message = self._check_rate_limit(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": message, "error": "rate_limit_exceeded"},
            )

        response = await call_next(request)
        return response
