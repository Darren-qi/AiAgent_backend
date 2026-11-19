"""
Utils 模块 __init__.py

导出所有工具函数。
"""

from app.utils.cache import (
    CacheManager,
    cache_manager,
    delete_cache,
    get_cache,
    set_cache,
)
from app.utils.logger import (
    app_logger,
    get_logger,
    log_critical,
    log_debug,
    log_error,
    log_exception,
    log_info,
    log_warning,
    setup_logger,
)

__all__ = [
    # Logger
    "setup_logger",
    "get_logger",
    "app_logger",
    "log_debug",
    "log_info",
    "log_warning",
    "log_error",
    "log_exception",
    "log_critical",
    # Cache
    "CacheManager",
    "cache_manager",
    "get_cache",
    "set_cache",
    "delete_cache",
]
