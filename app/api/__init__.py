"""
API 模块 __init__.py

导出 API 路由。
"""

from app.api.v1 import api_v1_router

__all__ = ["api_v1_router"]
