"""
FastAPI 应用入口模块

定义 FastAPI 应用实例，配置中间件、路由和生命周期事件。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.db.session import init_db, close_db
from app.api.v1.endpoints import (
    agent_router,
    session_router,
    storage_router,
    social_router,
    notification_router,
    budget_router,
    health_router,
    auth_router,
    websocket_router,
    users_router,
    posts_router,
)
from app.middleware.request_id import (
    RequestIDMiddleware,
    RequestTimingMiddleware,
    RequestLoggingMiddleware,
)
from app.utils.logger import setup_logger, log_info, log_error


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理器

    处理应用启动和关闭事件。
    """
    settings = get_settings()

    log_info(f"正在启动 {settings.app_name} v{settings.app_version}...")

    try:
        await init_db()
        log_info("数据库连接已建立")
    except Exception as e:
        log_error(f"数据库连接失败: {e}")

    log_info("应用启动完成")

    yield

    log_info("正在关闭应用...")
    await close_db()
    log_info("应用已关闭")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例"""
    settings = get_settings()

    setup_logger(
        log_level=settings.log_level,
        log_file_path=settings.log_file_path,
    )

    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=settings.debug,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestTimingMiddleware)

    if settings.is_development:
        app.add_middleware(RequestLoggingMiddleware, log_body=False, log_headers=False)

    app.include_router(agent_router, prefix="/api/v1/agent", tags=["Agent"])
    app.include_router(session_router, prefix="/api/v1/session", tags=["Session"])
    app.include_router(storage_router, prefix="/api/v1/storage", tags=["Storage"])
    app.include_router(social_router, prefix="/api/v1/social", tags=["Social"])
    app.include_router(notification_router, prefix="/api/v1/notification", tags=["Notification"])
    app.include_router(budget_router, prefix="/api/v1/budget", tags=["Budget"])
    app.include_router(health_router, prefix="/api/v1/health", tags=["Health"])
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    app.include_router(websocket_router, prefix="/api/v1/ws", tags=["WebSocket"])
    app.include_router(users_router, prefix="/api/v1/users", tags=["Users"])
    app.include_router(posts_router, prefix="/api/v1/posts", tags=["Posts"])

    @app.get("/health", tags=["系统"])
    async def health_check():
        """健康检查端点"""
        return {"status": "healthy", "app": settings.app_name, "version": settings.app_version}

    @app.get("/", tags=["系统"])
    async def root():
        """根路径"""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """处理应用自定义异常"""
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
            headers=exc.headers or {},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理 Pydantic 验证异常"""
        errors = []
        for error in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            })

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "请求参数验证失败", "error_code": "VALIDATION_ERROR", "details": errors},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的异常"""
        log_error(f"未处理的异常: {exc}", exc_info=True)

        if settings.is_production:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "服务器内部错误", "error_code": "INTERNAL_ERROR"},
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": str(exc), "error_code": "INTERNAL_ERROR", "type": type(exc).__name__},
            )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
