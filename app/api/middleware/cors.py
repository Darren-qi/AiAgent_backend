"""Middleware: CORS middleware."""

from fastapi.middleware.cors import CORSMiddleware as FastAPICORSMiddleware
from typing import List


def setup_cors_middleware(
    app,
    allow_origins: List[str] = None,
    allow_credentials: bool = True,
    allow_methods: List[str] = None,
    allow_headers: List[str] = None,
) -> None:
    """配置 CORS 中间件"""
    if allow_origins is None:
        allow_origins = ["*"]
    if allow_methods is None:
        allow_methods = ["*"]
    if allow_headers is None:
        allow_headers = ["*"]

    app.add_middleware(
        FastAPICORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )
