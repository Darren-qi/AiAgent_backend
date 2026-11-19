"""
日志配置模块

使用 loguru 配置应用日志，支持：
- 控制台输出（带颜色）
- 文件输出（自动轮转）
- 请求 ID 追踪
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(
    log_level: str = "INFO",
    log_file_path: str | None = None,
    enable_console: bool = True,
) -> None:
    """
    配置日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file_path: 日志文件路径（可选）
        enable_console: 是否启用控制台输出
    """
    # 移除默认的 handler
    logger.remove()

    # 阶段六：request_id 贯穿——patcher 给每条记录注入 contextvar 里的
    # 请求 ID（懒加载 import 防循环依赖：request_id 模块 import 本模块）
    def _patch_request_id(record: dict) -> None:
        try:
            from app.middleware.request_id import get_request_id
            rid = get_request_id()
        except Exception:  # noqa: BLE001 - 日志注入失败不影响记录本身
            rid = ""
        record["extra"]["request_id"] = rid or "-"

    logger.configure(patcher=_patch_request_id)

    # 配置日志格式
    # 包含时间、日志级别、模块名、行号、请求ID
    format_string = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>[{extra[request_id]}]</level> | "
        "<level>{message}</level>"
    )

    # 控制台输出
    if enable_console:
        logger.add(
            sys.stdout,
            format=format_string,
            level=log_level,
            colorize=True,
            backtrace=True,      # 显示完整的错误追溯
            diagnose=True,       # 显示变量值（调试用）
        )

    # 文件输出
    if log_file_path:
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # 按日期和大小轮转
        logger.add(
            log_path,
            format=format_string,
            level=log_level,
            rotation="10 MB",        # 达到 10MB 时轮转
            retention="30 days",    # 保留 30 天
            compression="zip",       # 压缩旧日志
            backtrace=True,
            diagnose=True,
        )

    # 设置全局日志级别
    logger.configure(handlers=[])


def get_logger(name: str | None = None):
    """
    获取日志记录器

    Args:
        name: 模块名称（用于标识日志来源）

    Returns:
        日志记录器实例
    """
    if name:
        return logger.bind(name=name)
    return logger


# 预配置的日志记录器
# 在 setup_logger() 被调用后使用
app_logger = logger


# =============================================
# 日志便捷函数
# =============================================

def log_debug(message: str, **kwargs) -> None:
    """记录 DEBUG 级别日志"""
    app_logger.debug(message, **kwargs)


def log_info(message: str, **kwargs) -> None:
    """记录 INFO 级别日志"""
    app_logger.info(message, **kwargs)


def log_warning(message: str, **kwargs) -> None:
    """记录 WARNING 级别日志"""
    app_logger.warning(message, **kwargs)


def log_error(message: str, **kwargs) -> None:
    """记录 ERROR 级别日志"""
    app_logger.error(message, **kwargs)


def log_exception(message: str, **kwargs) -> None:
    """记录异常日志（包含堆栈追溯）"""
    app_logger.exception(message, **kwargs)


def log_critical(message: str, **kwargs) -> None:
    """记录 CRITICAL 级别日志"""
    app_logger.critical(message, **kwargs)
