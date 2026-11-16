"""瞬态重试接线（阶段五，2026-11-17）。

计划 tool-harness-upgrade.md §阶段五：
- loader 层轻量重试：按 registry retry 元数据（search/search_files=1，写类=0），
  只重试 EXEC_FAILED/未分类失败，结构类拒绝不重试；
- 不复活 _execute_sequential_with_retry 死代码（已删除，grep 归零）。
"""

import pytest

from app.agent.skills.core.base_skill import SkillResult
from app.agent.skills.core.progressive_loader import get_loader
from app.agent.skills.guard import tool_guard


@pytest.fixture(autouse=True)
def _clean_guard():
    """熔断计数跨用例隔离（search 连续失败会污染同进程其他用例）。"""
    tool_guard.reset()
    yield
    tool_guard.reset()


async def test_transient_failure_retried_then_success(monkeypatch):
    """瞬态失败 1 次后成功：retry=1 的 search 调用 2 次，最终成功。"""
    loader = get_loader()
    calls = {"n": 0}

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return SkillResult(success=False, error="connection reset by peer")
        return SkillResult(success=True, data={"results": []})

    monkeypatch.setitem(loader._executors, "search", flaky)
    r = await loader.execute("search", {"query": "x"})
    assert r.success is True, r.error
    assert calls["n"] == 2, f"应重试 1 次，实际调用 {calls['n']} 次"


async def test_write_class_not_retried(monkeypatch):
    """写类（retry=0）瞬态失败不重试：只调 1 次。"""
    loader = get_loader()
    calls = {"n": 0}

    async def always_fail(**kw):
        calls["n"] += 1
        return SkillResult(success=False, error="disk hiccup")

    monkeypatch.setitem(loader._executors, "file_operations", always_fail)
    r = await loader.execute(
        "file_operations", {"operation": "read", "path": "a.py"})
    assert r.success is False
    assert calls["n"] == 1, f"retry=0 不得重试，实际调用 {calls['n']} 次"


async def test_retry_exhausted_returns_exec_failed(monkeypatch):
    """重试耗尽：retry=1 调满 2 次，回 EXEC_FAILED 进熔断计数。"""
    loader = get_loader()
    calls = {"n": 0}

    async def always_fail(**kw):
        calls["n"] += 1
        return SkillResult(success=False, error="timeout-ish io error")

    monkeypatch.setitem(loader._executors, "search", always_fail)
    r = await loader.execute("search", {"query": "x"})
    assert r.success is False
    assert r.error_code == "EXEC_FAILED"
    assert calls["n"] == 2, f"1+retry1 应共 2 次，实际 {calls['n']} 次"
    assert tool_guard.get_fail_count("search") == 1


async def test_structured_error_not_retried(monkeypatch):
    """结构类拒绝（MISSING_PARAM）确定性失败，不重试。"""
    loader = get_loader()
    calls = {"n": 0}

    async def missing(**kw):
        calls["n"] += 1
        return SkillResult(success=False, error="缺少 query 参数")

    monkeypatch.setitem(loader._executors, "search", missing)
    r = await loader.execute("search", {"query": ""})
    # 空串过契约（键存在）→ skill 内缺参 → 分类 MISSING_PARAM → 不重试
    assert r.success is False
    assert r.error_code == "MISSING_PARAM"
    assert calls["n"] == 1, f"结构类失败不得重试，实际 {calls['n']} 次"
