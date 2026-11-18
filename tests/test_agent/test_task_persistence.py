"""TaskManager 状态落库（阶段八 P1）：内存状态转移同步写 tasks 表。

覆盖：
1. persist_task_status 只 UPDATE、不建行；completed 不被覆盖（守卫在 SQL 里）
2. schedule_task_status 在事件循环里 fire-and-forget，异常吞掉
3. 终态转移点（stop/complete/fail）落库，create 只写内存（行创建即 running）
4. 没有事件循环时静默跳过；DB 挂了 fail-open 不影响状态转移
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import update
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Update

from app.agent import task_persistence as tp
from app.agent.task_executor import TaskManager, TaskStatus


class _FakeSession:
    """只记录 execute/commit 的假 session（当 async context manager 用）。"""

    def __init__(self, rec: list, error: Exception | None = None):
        self.rec = rec
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.rec.append(stmt)

    async def commit(self):
        self.rec.append("commit")


@pytest.fixture
def recorded(monkeypatch):
    """把 app.db.session.AsyncSessionLocal 换成记录型假工厂。"""
    rec: list = []
    err: list = []

    def factory():
        return _FakeSession(rec, err[0] if err else None)

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", factory)
    return {"rec": rec, "err": err}


def _status_of(stmt):
    return stmt.compile(dialect=postgresql.dialect()).params.get("status")


def _where_sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestPersistTaskStatus:
    @pytest.mark.asyncio
    async def test_updates_existing_row_only(self, recorded):
        await tp.persist_task_status("t-1", "failed", "boom")

        stmts = [s for s in recorded["rec"] if s != "commit"]
        assert len(stmts) == 1, "只 UPDATE 一次，不 INSERT"
        stmt = stmts[0]
        assert isinstance(stmt, Update)
        assert _status_of(stmt) == "failed"
        assert "tasks" in _where_sql(stmt)
        # 失败原因要落进去
        assert stmt.compile(dialect=postgresql.dialect()).params["error"] == "boom"
        assert recorded["rec"][-1] == "commit"

    @pytest.mark.asyncio
    async def test_completed_is_not_overwritten(self, recorded):
        """终态守卫：非 completed 的写必须带 status != completed 条件。"""
        await tp.persist_task_status("t-1", "running")
        running_sql = _where_sql(recorded["rec"][0])
        assert "tasks.status !=" in running_sql or "tasks.status <> " in running_sql

        recorded["rec"].clear()
        await tp.persist_task_status("t-1", "completed")
        completed_sql = _where_sql(recorded["rec"][0])
        assert "tasks.status !=" not in completed_sql
        assert "tasks.status <> " not in completed_sql

    @pytest.mark.asyncio
    async def test_no_task_id_is_noop(self, recorded):
        await tp.persist_task_status("", "failed")
        assert recorded["rec"] == []

    @pytest.mark.asyncio
    async def test_db_failure_is_fail_open(self, recorded):
        recorded["err"].append(RuntimeError("db down"))
        # 绝不抛：落库失败不能影响任务执行
        await tp.persist_task_status("t-1", "failed", "x")


class TestScheduleTaskStatus:
    @pytest.mark.asyncio
    async def test_schedules_and_lands(self, recorded):
        tp.schedule_task_status("t-1", "stopped")
        for _ in range(10):
            await asyncio.sleep(0)
        statuses = [_status_of(s) for s in recorded["rec"]
                    if s != "commit" and isinstance(s, Update)]
        assert statuses == ["stopped"]
        assert tp.pending_count() == 0, "落完要从 pending 集合摘掉"

    def test_no_running_loop_is_silent(self, recorded):
        # 纯同步上下文：没有事件循环 → 跳过，不抛
        tp.schedule_task_status("t-1", "failed")
        assert recorded["rec"] == []


class TestTaskManagerPersists:
    def setup_method(self):
        # TaskManager 是单例，测试间清干净
        TaskManager._instance = None
        self.mgr = TaskManager()
        self.mgr._tasks.clear()

    @pytest.mark.asyncio
    async def test_terminal_transitions_land(self, recorded, monkeypatch):
        """终态（stopped/completed/failed）落库；create 只写内存 ——
        行创建时就是 running，再写一次只会在启动期多抢连接。"""
        calls: list = []
        monkeypatch.setattr(
            tp, "schedule_task_status",
            lambda tid, st, err="": calls.append((tid, st, err)))

        self.mgr.create_task("t-9")
        assert calls == [], "create 不落库"
        assert self.mgr.get_status("t-9") == TaskStatus.RUNNING, "内存态照常"

        self.mgr.stop_task("t-9")
        self.mgr.complete_task("t-9")
        self.mgr.fail_task("t-9")

        assert [c[1] for c in calls] == ["stopped", "completed", "failed"]
        assert all(c[0] == "t-9" for c in calls)
        # 内存态照常
        assert self.mgr.get_status("t-9") == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_unknown_task_not_persisted(self, recorded, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            tp, "schedule_task_status",
            lambda tid, st, err="": calls.append((tid, st)))
        assert self.mgr.stop_task("nope") is False
        assert calls == []
