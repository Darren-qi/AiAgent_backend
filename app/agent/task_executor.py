"""
Task Manager - 任务状态管理模块

提供内存任务状态管理（支持中断）。
被 agent.py 和 main_graph.py 使用。
"""

import logging
from enum import Enum
from typing import Any

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
    - 内存存储为主：进程内查询用它；状态转移同时同步到 tasks 表
      （fire-and-forget，见 app/agent/task_persistence.py），
      进程退出后 tasks.status 仍是最新值
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
        self._tasks: dict[str, dict[str, Any]] = {}
        self._initialized = True
        logger.info("[TaskManager] 已初始化")

    @staticmethod
    def _persist(task_id: str, status: Any, error: str = "") -> None:
        """状态转移同步到 tasks 表（阶段八 P1）。

        内存态只服务进程内查询；进程一退就丢。落库是 fire-and-forget
        且 fail-open（见 app/agent/task_persistence.py），绝不影响状态转移本身。
        """
        try:
            from app.agent.task_persistence import schedule_task_status

            schedule_task_status(
                task_id, str(getattr(status, "value", status)), error)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[TaskManager] 状态落库调度失败 task={task_id}: {e}")

    def create_task(self, task_id: str) -> None:
        """创建新任务（只写内存，不落库）。

        落库的 running 不需要这里写：行本来就是以 running 建的
        （main_graph._save_execution_node / 接口创建任务），再写一次纯冗余。
        终态（stopped/completed/failed）才同步落库。
        """
        self._tasks[task_id] = {
            "status": TaskStatus.RUNNING,
        }
        logger.debug(f"[TaskManager] 创建任务: {task_id}")

    def stop_task(self, task_id: str) -> bool:
        """请求停止任务"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = TaskStatus.STOPPED
            self._persist(task_id, TaskStatus.STOPPED)
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
            self._persist(task_id, TaskStatus.COMPLETED)
            logger.debug(f"[TaskManager] 任务完成: {task_id}")

    def fail_task(self, task_id: str) -> None:
        """标记任务失败"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = TaskStatus.FAILED
            self._persist(task_id, TaskStatus.FAILED)
            logger.debug(f"[TaskManager] 任务失败: {task_id}")

    def remove_task(self, task_id: str) -> None:
        """移除任务"""
        self._tasks.pop(task_id, None)

    def get_all_tasks(self) -> dict[str, str]:
        """获取所有任务状态"""
        return {tid: info["status"] for tid, info in self._tasks.items()}


# 全局单例
task_manager = TaskManager()
