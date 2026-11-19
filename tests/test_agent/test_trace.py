"""JSONL run 日志 + duration 落库链（阶段六 Trace，2026-11-17）。

计划 tool-harness-upgrade.md §阶段六验收：
一次失败调用能从三处交叉定位——DB（execution_nodes.meta_data）、
JSONL（logs/runs/）、日志（app.log 含 model/latency）。
本文件覆盖 JSONL 与 duration 链；LLM 打点见 test_llm/test_llm_trace.py。
"""

import json

import pytest

from app.agent import trace as trace_mod
from app.agent.skills.core.progressive_loader import get_loader
from app.agent.skills.guard import tool_guard
from app.agent.trace import configure_run_log, params_digest, run_log


@pytest.fixture(autouse=True)
def _run_log_tmp(tmp_path, monkeypatch):
    """run 日志重定向到 tmp，避免污染 logs/runs；结束后清熔断计数。"""
    trace_mod._state["path"] = tmp_path / "run.jsonl"
    trace_mod._state["session_id"] = "test"
    tool_guard.reset()
    yield
    trace_mod._state["path"] = None
    trace_mod._state["session_id"] = None
    tool_guard.reset()


def test_configure_disables_without_session():
    configure_run_log(None)
    assert trace_mod.get_run_log_path() is None
    run_log("tool_call", tool="x")  # no-op 不炸
    assert trace_mod.get_run_log_path() is None


def test_configure_creates_session_file_pattern(tmp_path):
    """真实 configure：路径形如 logs/runs/{session}_{ts}.jsonl（用后即删）。"""
    configure_run_log("trace_unit_session")
    p = trace_mod.get_run_log_path()
    try:
        assert p is not None and p.parent.name == "runs"
        assert p.name.startswith("trace_unit_session_") and p.suffix == ".jsonl"
    finally:
        if p and p.exists():
            p.unlink()
        trace_mod._state["path"] = None


def test_run_log_writes_event_with_request_id():
    run_log("tool_call", tool="search", ok=False, error_code="EXEC_FAILED")
    path = trace_mod.get_run_log_path()
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    assert len(recs) == 1
    ev = recs[0]
    assert ev["event"] == "tool_call"
    assert ev["tool"] == "search" and ev["error_code"] == "EXEC_FAILED"
    assert "request_id" in ev  # 中间件 contextvar 贯穿（无请求时为 None）
    assert isinstance(ev["ts"], float)


def test_params_digest_stores_no_content():
    """params 只存摘要（键名+大小），不存全文——防日志爆炸。"""
    d = params_digest({"content": "X" * 50000, "path": "a.py"})
    assert d["keys"] == ["content", "path"]
    assert d["size"] > 50000
    assert "content" not in json.dumps(d) or "X" not in json.dumps(d)


def test_guard_finish_returns_duration_event():
    """finish 返回审计事件（阶段六：duration 供落库）。"""
    assert tool_guard.begin("search", {"query": "q"}) is None
    ev = tool_guard.finish("search", ok=False, detail="boom",
                           error_code="EXEC_FAILED")
    assert isinstance(ev, dict)
    assert ev["duration_ms"] is None or isinstance(ev["duration_ms"], float)
    assert ev["error_code"] == "EXEC_FAILED"


async def test_loader_attaches_duration_and_emits_run_log(monkeypatch):
    """loader 出口：duration 挂 SkillResult.metadata + JSONL 记 tool_call。"""
    from app.agent.skills.core.base_skill import SkillResult

    loader = get_loader()

    async def fast(**kw):
        return SkillResult(success=True, data={"ok": True})

    monkeypatch.setitem(loader._executors, "search", fast)
    r = await loader.execute("search", {"query": "q"})
    assert r.success
    assert isinstance(r.metadata.get("duration_ms"), (int, float))

    recs = [json.loads(l) for l in
            trace_mod.get_run_log_path().read_text().splitlines()]
    tool_calls = [e for e in recs if e["event"] == "tool_call"]
    assert tool_calls, f"缺 tool_call 事件: {recs}"
    ev = tool_calls[-1]
    assert ev["tool"] == "search" and ev["ok"] is True
    assert isinstance(ev["params"], dict) and "keys" in ev["params"]


async def test_guard_deny_emits_run_log():
    """守卫拒绝也进 JSONL（guard_deny 事件）。"""
    from app.agent.skills.core.progressive_loader import get_loader
    r = await get_loader().execute("ghost_skill_zz", {})
    assert r.error_code == "UNKNOWN_SKILL"
    recs = [json.loads(l) for l in
            trace_mod.get_run_log_path().read_text().splitlines()]
    denies = [e for e in recs if e["event"] == "guard_deny"]
    assert denies and denies[-1]["error_code"] == "UNKNOWN_SKILL"
