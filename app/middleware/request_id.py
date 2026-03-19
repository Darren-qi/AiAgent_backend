"""
请求 ID 中间件模块

为每个请求生成唯一的请求 ID，方便日志追踪和调试。
支持：
- 自动生成 UUID 请求 ID
- 将请求 ID 添加到响应头
- 在日志中记录请求 ID
"""

import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.utils.logger import log_info, log_debug, log_error


# 上下文变量，用于在日志中记录请求 ID
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """
    获取当前请求的 ID

    在请求处理过程中可调用此函数获取请求 ID。
    """
    return request_id_ctx.get()


def get_request_id_header(request: Request) -> str:
    """
    从请求头获取请求 ID

    如果请求头中没有，则生成新的。
    支持的请求头名称：
    - X-Request-ID（标准）
    - X-Correlation-ID（某些系统使用）
    - Request-ID（某些系统使用）
    """
    return (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Correlation-ID")
        or request.headers.get("Request-ID")
        or str(uuid.uuid4())
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    请求 ID 中间件

    为每个请求生成唯一的请求 ID，并：
    - 将其存储在上下文变量中（用于日志）
    - 添加到响应头的 X-Request-ID 字段
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # 获取或生成请求 ID
        request_id = get_request_id_header(request)

        # 存储到上下文变量
        token = request_id_ctx.set(request_id)

        # 添加到请求状态（方便在路由处理器中访问）
        request.state.request_id = request_id

        # 添加到响应头
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        # 恢复上下文
        request_id_ctx.reset(token)

        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """
    请求计时中间件

    记录每个请求的处理时间，便于性能分析和优化。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # 记录开始时间
        start_time = time.perf_counter()

        # 处理请求
        response = await call_next(request)

        # 计算耗时
        elapsed = (time.perf_counter() - start_time) * 1000  # 转换为毫秒

        # 添加到响应头
        response.headers["X-Process-Time"] = f"{elapsed:.2f}ms"

        # 记录日志
        log_info(
            f"{request.method} {request.url.path} - {response.status_code} - {elapsed:.2f}ms"
        )

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求日志中间件

    记录所有请求的详细信息，便于调试和审计。
    """

    def __init__(
        self,
        app: ASGIApp,
        log_body: bool = False,
        log_headers: bool = False,
    ):
        super().__init__(app)
        self.log_body = log_body
        self.log_headers = log_headers

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # 获取请求 ID
        request_id = getattr(request.state, "request_id", "unknown")

        # 记录请求信息
        log_info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )

        # 记录请求头（如果启用）
        if self.log_headers:
            log_debug(f"[{request_id}] Request headers: {dict(request.headers)}")

        # 记录请求体（如果启用，且不为 multipart）
        if self.log_body and request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.body()
                if body:
                    log_debug(f"[{request_id}] Request body: {body.decode()}")

        # 处理请求
        try:
            response = await call_next(request)

            # 记录响应状态
            log_info(
                f"[{request_id}] Response: {response.status_code}"
            )

            return response

        except Exception as e:
            # 记录错误
            log_error(
                f"[{request_id}] Request failed: {str(e)}",
                exc_info=True,
            )
            raise
