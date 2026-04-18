"""
可取消信号管理器

提供全局取消状态管理，支持 LLM 调用期间检查取消信号。
"""

import asyncio
import logging
from typing import Optional, Callable, Coroutine, Any

logger = logging.getLogger(__name__)


class CancelSignalManager:
    """
    全局取消信号管理器

    使用方式：
    1. 在任务开始时注册：CancelSignal.register(task_id)
    2. 在任务结束时注销：CancelSignal.unregister(task_id)
    3. 在需要取消时调用：CancelSignal.cancel(task_id)
    4. 在 LLM 调用时检查：CancelSignal.is_cancelled(task_id)
    """

    _instance: Optional["CancelSignalManager"] = None
    _cancelled_tasks: set = set()
    _lock: asyncio.Lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = asyncio.Lock()
            cls._instance._cancelled_tasks = set()
        return cls._instance

    @classmethod
    def register(cls, task_id: str) -> None:
        """注册任务"""
        instance = cls()
        instance._cancelled_tasks.discard(task_id)
        logger.debug(f"[CancelSignal] 注册任务: {task_id}")

    @classmethod
    def unregister(cls, task_id: str) -> None:
        """注销任务"""
        instance = cls()
        instance._cancelled_tasks.discard(task_id)
        logger.debug(f"[CancelSignal] 注销任务: {task_id}")

    @classmethod
    def cancel(cls, task_id: str) -> bool:
        """请求取消任务"""
        instance = cls()
        if task_id in instance._cancelled_tasks:
            return False
        instance._cancelled_tasks.add(task_id)
        logger.info(f"[CancelSignal] 取消任务: {task_id}")
        return True

    @classmethod
    def is_cancelled(cls, task_id: str) -> bool:
        """检查任务是否已取消"""
        instance = cls()
        return task_id in instance._cancelled_tasks

    @classmethod
    def reset(cls) -> None:
        """重置所有取消状态"""
        instance = cls()
        instance._cancelled_tasks.clear()


# 全局单例
cancel_signal = CancelSignalManager()


async def cancellable_wait_for(
    coro: Coroutine,
    timeout: float,
    task_id: str,
    poll_interval: float = 0.5,
) -> Any:
    """
    可取消的 wait_for

    在 timeout 周期内定期检查取消状态，一旦检测到取消，立即抛出 CancelledError。

    这个函数只执行一次协程调用，通过 asyncio.wait_for 的 timeout 机制
    配合 asyncio.CancelledError 的转换来实现可取消。

    Args:
        coro: 协程（必须是尚未 await 的协程对象）
        timeout: 超时时间（秒）
        task_id: 任务 ID（用于检查取消状态）
        poll_interval: 取消状态检查间隔（当前未使用，保留兼容性）

    Returns:
        协程结果

    Raises:
        asyncio.CancelledError: 任务被取消
        asyncio.TimeoutError: 任务超时
    """
    check_interval = min(poll_interval, timeout) if timeout > 0 else poll_interval
    total_waited = 0.0

    # 包装协程，记录是否为 cancelled
    cancelled = False

    while True:
        # 先检查是否已取消
        if cancel_signal.is_cancelled(task_id):
            logger.info(f"[CancelSignal] 检测到取消信号: {task_id}")
            raise asyncio.CancelledError(f"Task {task_id} was cancelled")

        try:
            # 使用 asyncio.wait_for 等待一段时间
            result = await asyncio.wait_for(coro, timeout=check_interval)
            return result
        except asyncio.TimeoutError:
            total_waited += check_interval
            # 如果总等待时间已达到超时，抛出超时错误
            if total_waited >= timeout:
                # 再次检查取消状态
                if cancel_signal.is_cancelled(task_id):
                    raise asyncio.CancelledError(f"Task {task_id} was cancelled")
                logger.warning(f"[CancelSignal] LLM 调用超时: {task_id}")
                raise asyncio.TimeoutError(f"LLM call timed out after {timeout}s")
            # 继续等待，同时检查取消
            continue
        except asyncio.CancelledError:
            # 如果是取消错误，直接传播
            raise


async def cancellable_chat(
    coro_factory: Callable[[], Coroutine],
    task_id: str,
    timeout: float = 60.0,
) -> Any:
    """
    可取消的聊天调用（简单版）

    直接调用协程，通过 asyncio.wait_for 实现超时和取消检测。

    注意：这个函数会直接调用 factory 创建协程并等待，
    取消检测依赖 asyncio.wait_for 的超时机制。

    Args:
        coro_factory: 返回协程的工厂函数
        task_id: 任务 ID
        timeout: 超时时间（秒）

    Returns:
        LLM 响应
    """
    # 检查是否已取消
    if cancel_signal.is_cancelled(task_id):
        raise asyncio.CancelledError(f"Task {task_id} was cancelled")

    # 使用 asyncio.wait_for 实现超时
    # 取消依赖 asyncio.Task.cancel() 的机制
    coro = coro_factory()

    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        # 检查是否被取消
        if cancel_signal.is_cancelled(task_id):
            raise asyncio.CancelledError(f"Task {task_id} was cancelled")
        logger.warning(f"[CancelSignal] LLM 调用超时: {task_id}")
        raise
