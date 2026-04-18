"""
数据库会话模块

配置异步数据库引擎和会话工厂。
使用 SQLAlchemy 2.0 异步 API，支持 PostgreSQL。
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

# 获取配置实例
settings = get_settings()

# =============================================
# 异步引擎配置
# =============================================

def create_async_db_engine() -> AsyncEngine:
    """
    创建异步数据库引擎

    使用 asyncpg 作为 PostgreSQL 异步驱动。
    生产环境启用连接池，开发环境使用 NullPool 便于调试。
    """
    if settings.is_production:
        # 生产环境：启用连接池
        engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,                    # 仅调试模式下打印 SQL
            pool_size=settings.db_pool_size,        # 基础连接数
            max_overflow=settings.db_max_overflow,  # 允许的额外连接数
            pool_pre_ping=True,                     # 连接前检测有效性
            pool_recycle=3600,                      # 连接回收时间（秒）
        )
    else:
        # 开发环境：使用 NullPool 避免连接占用问题
        engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            poolclass=NullPool,
        )

    return engine


# 创建全局引擎实例
engine = create_async_db_engine()

# =============================================
# 会话工厂配置
# =============================================

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,      # 提交后不自动过期对象，便于调试
    autoflush=False,             # 需要手动 flush
    autocommit=False,            # 需要手动提交
)


# =============================================
# 兼容性别名 (供旧代码使用)
# =============================================

@asynccontextmanager
async def async_session():
    """
    兼容性别别 - 用于需要 async generator 的场景

    使用示例:
        async for session in async_session():
            # 使用 session
    """
    async with AsyncSessionLocal() as session:
        yield session


# =============================================
# 会话依赖注入
# =============================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    依赖注入函数：获取数据库会话

    用于 FastAPI 路径函数的依赖注入。
    确保每个请求使用独立的会话，请求结束后自动关闭。

    使用示例:
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            # 将会话传递给路由处理器
            yield session
        finally:
            # 请求结束后关闭会话
            await session.close()


# =============================================
# 事务上下文管理器
# =============================================

@asynccontextmanager
async def get_db_transaction() -> AsyncGenerator[AsyncSession, None]:
    """
    事务上下文管理器

    在事务中执行操作，自动处理提交和回滚。
    异常发生时自动回滚，正常结束时自动提交。

    使用示例:
        async with get_db_transaction() as db:
            db.add(user)
            db.add(post)
            # 异常时自动回滚
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                # 事务已自动回滚，无需手动处理
                raise


# =============================================
# 数据库初始化和清理
# =============================================

async def init_db() -> None:
    """
    初始化数据库

    在应用启动时调用，创建所有表结构。
    生产环境建议使用 Alembic 进行数据库迁移。
    """
    from app.db.base import Base

    # 导入所有模型以确保它们被注册到 Base.metadata
    from app.models import user, post  # noqa: F401

    async with engine.begin() as conn:
        # 创建所有表（如果不存在）
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    关闭数据库连接

    在应用关闭时调用，释放所有连接池资源。
    """
    await engine.dispose()
