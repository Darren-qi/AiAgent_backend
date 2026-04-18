"""
Task Manager - 任务状态管理模块

提供内存任务状态管理（支持中断）。
被 agent.py 和 main_graph.py 使用。
"""

import asyncio
import logging
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class TaskManager:
    """
    内存任务状态管理器

    职责：
    - 管理任务运行状态（running/stopped/completed/failed）
    - 响应中断请求
    - 提供状态查询

    注意：
    - 仅管理状态，不处理业务逻辑
    - 纯内存存储，不持久化（持久化由 ExecutionStateManager 处理）
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._initialized = True
        logger.info("[TaskManager] 已初始化")

    def create_task(self, task_id: str) -> None:
        """创建新任务"""
        self._tasks[task_id] = {
            "status": TaskStatus.RUNNING,
        }
        logger.debug(f"[TaskManager] 创建任务: {task_id}")

    def stop_task(self, task_id: str) -> bool:
        """请求停止任务"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = TaskStatus.STOPPED
            logger.info(f"[TaskManager] 请求停止任务: {task_id}")
            return True
        logger.warning(f"[TaskManager] 任务不存在: {task_id}")
        return False

    def is_running(self, task_id: str) -> bool:
        """检查任务是否在运行"""
        return self._tasks.get(task_id, {}).get("status") == TaskStatus.RUNNING

    def get_status(self, task_id: str) -> str:
        """获取任务状态"""
        return self._tasks.get(task_id, {}).get("status", TaskStatus.PENDING)

    def complete_task(self, task_id: str) -> None:
        """标记任务完成"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = TaskStatus.COMPLETED
            logger.debug(f"[TaskManager] 任务完成: {task_id}")

    def fail_task(self, task_id: str) -> None:
        """标记任务失败"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = TaskStatus.FAILED
            logger.debug(f"[TaskManager] 任务失败: {task_id}")

    def remove_task(self, task_id: str) -> None:
        """移除任务"""
        self._tasks.pop(task_id, None)

    def get_all_tasks(self) -> Dict[str, str]:
        """获取所有任务状态"""
        return {tid: info["status"] for tid, info in self._tasks.items()}


# 全局单例
task_manager = TaskManager()
