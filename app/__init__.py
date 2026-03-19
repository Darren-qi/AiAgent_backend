"""
App 模块 __init__.py

FastAPI 应用包初始化。
"""

from app.main import app, create_app

__all__ = ["app", "create_app"]
