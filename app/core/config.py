"""
Pydantic 配置模块

定义应用配置，支持开发和生产两套配置。
核心变量从根目录 config.py 加载，其余使用默认值。
"""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import config as dev_config


def _build_database_url(db: dict, async_driver: bool = True) -> str:
    """构建数据库连接 URL"""
    driver = "postgresql+asyncpg" if async_driver else "postgresql"
    return f"{driver}://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"


class Settings(BaseSettings):
    """
    应用配置类

    核心变量从根目录 config.py 加载，其余使用默认值。
    """

    model_config = SettingsConfigDict(
        extra="ignore",  # 忽略额外字段
    )

    # =========================================
    # 应用信息
    # =========================================
    app_name: str = Field(default="ai-agent-backend", description="应用名称")
    app_version: str = Field(default="1.0.0", description="应用版本")
    app_description: str = Field(default="AI Agent Backend API", description="应用描述")

    # 环境标识: development | production
    environment: str = Field(default="development", description="运行环境")

    # 调试模式（生产环境应设为 False）
    debug: bool = Field(default=True, description="是否开启调试模式")

    # 允许的 CORS 源（逗号分隔）
    allowed_origins: str = Field(default="http://localhost:3000", description="允许的CORS源")

    @property
    def cors_origins(self) -> List[str]:
        """解析 CORS 源字符串为列表"""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """判断是否为生产环境"""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """判断是否为开发环境"""
        return self.environment == "development"

    # =========================================
    # 服务器配置
    # =========================================
    host: str = Field(default="0.0.0.0", description="服务器主机")
    port: int = Field(default=8000, ge=1, le=65535, description="服务器端口")

    # =========================================
    # 数据库配置
    # =========================================
    # 异步数据库连接（用于 FastAPI 异步操作）
    database_url: str = Field(
        default=_build_database_url(dev_config.database, async_driver=True),
        description="异步数据库连接URL"
    )

    # 同步数据库连接（用于 Alembic 迁移）
    database_url_sync: str = Field(
        default=_build_database_url(dev_config.database, async_driver=False),
        description="同步数据库连接URL"
    )

    # 连接池配置
    db_pool_size: int = Field(default=10, ge=1, description="数据库连接池大小")
    db_max_overflow: int = Field(default=20, ge=0, description="数据库连接池最大溢出")

    # =========================================
    # Redis 配置
    # =========================================
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis连接URL")
    cache_expire_seconds: int = Field(default=3600, ge=0, description="缓存过期时间(秒)")

    # =========================================
    # JWT 认证配置
    # =========================================
    secret_key: str = Field(
        default=dev_config.secret_key,
        description="JWT签名密钥"
    )
    algorithm: str = Field(
        default=dev_config.algorithm,
        description="JWT加密算法"
    )

    # Token 过期时间
    access_token_expire_minutes: int = Field(
        default=dev_config.access_token_expire_minutes,
        ge=1,
        description="访问令牌过期时间(分钟)"
    )
    refresh_token_expire_days: int = Field(
        default=dev_config.refresh_token_expire_days,
        ge=1,
        description="刷新令牌过期时间(天)"
    )

    # =========================================
    # 邮件配置（可选功能）
    # =========================================
    smtp_host: str = Field(default="", description="SMTP服务器地址")
    smtp_port: int = Field(default=587, description="SMTP服务器端口")
    smtp_user: str = Field(default="", description="SMTP用户名")
    smtp_password: str = Field(default="", description="SMTP密码")
    emails_from_email: str = Field(default="", description="发件人邮箱")

    @property
    def smtp_enabled(self) -> bool:
        """判断 SMTP 是否已配置"""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    # =========================================
    # 日志配置
    # =========================================
    log_level: str = Field(default="INFO", description="日志级别")
    log_file_path: str = Field(default="logs/app.log", description="日志文件路径")

    # =========================================
    # 配置验证
    # =========================================
    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """验证环境标识"""
        allowed = {"development", "production", "staging", "test"}
        if v not in allowed:
            raise ValueError(f"environment 必须是 {allowed} 之一")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证日志级别"""
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"log_level 必须是 {allowed} 之一")
        return v_upper


@lru_cache()  # 缓存配置实例，避免重复读取环境变量
def get_settings() -> Settings:
    """
    获取配置单例

    使用 lru_cache 缓存配置实例，整个应用生命周期内只加载一次。
    """
    return Settings()
