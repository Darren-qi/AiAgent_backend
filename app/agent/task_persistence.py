"""tasks 表状态落库通道（阶段八 P1）。

TaskManager 原本只在内存里记 running/stopped/completed/failed：
进程一退就丢，tasks.status 永远停在 running —— 只有启动时的
sweep_orphan_tasks() 能兜底，而且要等 2 小时。把状态转移同步写进
库里，外部查询任务状态看到的就是实时值。

规则与原来的 api.agent._finalize_db_task 保持一致（实现只留一份，
那处已改为转调这里）：
- 只 UPDATE 不 INSERT：行由 main_graph / 接口创建，落库只负责状态
- completed 不被覆盖：已完成的任务不因客户端断连/取消被改成 failed
- 全程 fail-open：写失败只 WARNING，绝不影响任务执行
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Set

logger = logging.getLogger(__name__)

# 保持 fire-and-forget 协程的引用，避免被 GC 掉（"Task was destroyed"）
_pending: Set[asyncio.Task] = set()


async def persist_task_status(task_id: str, status: str, error: str = "") -> None:
    """把任务状态写进 tasks 表（只 UPDATE 不 INSERT）。"""
    if not task_id or not status:
        return
    try:
        from sqlalchemy import update

        from app.db.session import AsyncSessionLocal
        from app.models.experience import TaskModel

        async with AsyncSessionLocal() as s:
            stmt = (
                update(TaskModel)
                .where(TaskModel.task_id == task_id)
                .values(
                    status=status,
                    error=error or "",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            if status != "completed":
                # 已完成的任务不被"取消/断连/超时"覆盖成别的终态
                stmt = stmt.where(TaskModel.status != "completed")
            await s.execute(stmt)
            await s.commit()
        logger.debug(f"[TaskPersist] 任务状态已落库: {task_id} -> {status}")
    except Exception as e:  # noqa: BLE001 - fail-open
        logger.warning(f"[TaskPersist] 写任务状态失败 task={task_id} status={status}: {e}")


def schedule_task_status(task_id: str, status: str, error: str = "") -> None:
    """状态转移入口（同步）：有运行中的事件循环就 fire-and-forget，否则跳过。

    TaskManager 的状态转移都是同步调用（FastAPI 处理器、图节点里都可能调），
    DB 写是异步的 → 只能挂成后台任务；失败不影响主流程。
    """
    if not task_id or not status:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有事件循环（纯同步上下文）：跳过，交给启动时的 orphan sweep 兜底
        logger.debug(f"[TaskPersist] 无事件循环，跳过落库 task={task_id} status={status}")
        return
    task = loop.create_task(persist_task_status(task_id, status, error))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def pending_count() -> int:
    """还在飞的落库协程数（测试/诊断用）。"""
    return len(_pending)
