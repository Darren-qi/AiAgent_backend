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
from app.core.security import verify_access_token
from app.db.session import init_db, close_db
from app.api.v1 import api_v1_router
from app.middleware.request_id import (
    RequestIDMiddleware,
    RequestTimingMiddleware,
    RequestLoggingMiddleware,
)
from app.utils.logger import setup_logger, log_info, log_error


# =============================================
# 应用生命周期管理
# =============================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    应用生命周期管理器

    处理应用启动和关闭事件：
    - 启动：初始化数据库、连接缓存
    - 关闭：关闭数据库连接、刷新日志
    """
    settings = get_settings()

    # ===== 启动时执行 =====
    log_info(f"正在启动 {settings.app_name} v{settings.app_version}...")

    # 初始化数据库
    try:
        await init_db()
        log_info("数据库连接已建立")
    except Exception as e:
        log_error(f"数据库连接失败: {e}")
        # 可根据需要决定是否继续启动

    # 连接 Redis 缓存
    # try:
    #     from app.utils.cache import cache_manager
    #     await cache_manager.connect()
    #     log_info("Redis 连接已建立")
    # except Exception as e:
    #     log_error(f"Redis 连接失败: {e}")

    log_info("应用启动完成")

    yield

    # ===== 关闭时执行 =====
    log_info("正在关闭应用...")

    # 关闭数据库连接
    await close_db()
    log_info("数据库连接已关闭")

    # 关闭 Redis 连接
    # try:
    #     from app.utils.cache import cache_manager
    #     await cache_manager.disconnect()
    #     log_info("Redis 连接已关闭")
    # except Exception:
    #     pass

    log_info("应用已关闭")


# =============================================
# 创建应用实例
# =============================================

def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例

    Returns:
        配置完成的 FastAPI 应用
    """
    settings = get_settings()

    # 初始化日志
    setup_logger(
        log_level=settings.log_level,
        log_file_path=settings.log_file_path,
    )

    # 创建 FastAPI 应用
    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        docs_url="/docs",              # Swagger UI
        redoc_url="/redoc",            # ReDoc
        openapi_url="/openapi.json",   # OpenAPI schema
        lifespan=lifespan,
        # 生产环境关闭详细错误信息
        debug=settings.debug,
    )

    # =========================================
    # 注册中间件
    # =========================================

    # CORS 中间件（跨域资源共享）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求 ID 中间件
    app.add_middleware(RequestIDMiddleware)

    # 请求计时中间件
    app.add_middleware(RequestTimingMiddleware)

    # 请求日志中间件（可选，仅开发环境启用）
    if settings.is_development:
        app.add_middleware(
            RequestLoggingMiddleware,
            log_body=False,
            log_headers=False,
        )

    # =========================================
    # 注册路由
    # =========================================

    # API 路由
    app.include_router(api_v1_router)

    # 健康检查端点
    @app.get("/health", tags=["系统"])
    async def health_check():
        """
        健康检查端点

        用于负载均衡器和容器编排系统的健康探测。
        """
        return {
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
        }

    # 根路径
    @app.get("/", tags=["系统"])
    async def root():
        """
        根路径

        返回应用基本信息。
        """
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    # =========================================
    # 注册异常处理器
    # =========================================

    # 自定义应用异常
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """处理应用自定义异常"""
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
            headers=exc.headers or {},
        )

    # 请求验证异常
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
            content={
                "error": "请求参数验证失败",
                "error_code": "VALIDATION_ERROR",
                "details": errors,
            },
        )

    # 通用异常处理器
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理未捕获的异常"""
        log_error(f"未处理的异常: {exc}", exc_info=True)

        # 生产环境隐藏详细错误信息
        if settings.is_production:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "服务器内部错误",
                    "error_code": "INTERNAL_ERROR",
                },
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": str(exc),
                    "error_code": "INTERNAL_ERROR",
                    "type": type(exc).__name__,
                },
            )

    return app


# =============================================
# 应用实例
# =============================================

app = create_app()


# =============================================
# 运行应用（开发模式）
# =============================================

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
