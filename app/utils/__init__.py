"""
Utils 模块 __init__.py

导出所有工具函数。
"""

from app.utils.logger import (
    setup_logger,
    get_logger,
    app_logger,
    log_debug,
    log_info,
    log_warning,
    log_error,
    log_exception,
    log_critical,
)
from app.utils.cache import (
    CacheManager,
    cache_manager,
    get_cache,
    set_cache,
    delete_cache,
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
