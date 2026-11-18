"""ToolGuard 执行前守卫（阶段三，2026-11-17）。

计划 tool-harness-upgrade.md §阶段三验收：
传参类错误在 guard 层被拦并回注结构化 code，不再穿透到 skill 内手工 if。
"""

import pytest

from app.agent.skills.guard import tool_guard
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clean_guard(monkeypatch):
    """每个用例前清空单例状态，结束后恢复全局设置。"""
    tool_guard.reset()
    monkeypatch.setattr(get_settings(), "tool_approval_mode", "auto")
    monkeypatch.setattr(get_settings(), "tool_consecutive_fail_limit", 2)
    yield
    tool_guard.reset()


def test_unknown_skill_rejected():
    d = tool_guard.begin("no_such_skill_xyz", {"foo": 1})
    assert d is not None
    assert d["error_code"] == "UNKNOWN_SKILL"
    assert "未注册" in d["message"]


def test_missing_param_rejected():
    """契约缺参在 guard 层拦截（不再穿透到 skill 内手工 if）。"""
    d = tool_guard.begin(
        "file_operations", {"operation": "write", "content": "x"})
    assert d is not None
    assert d["error_code"] == "MISSING_PARAM"
    assert "参数结构异常" in d["message"]  # TC-S16-04 文案契约保留


def test_invalid_type_rejected():
    """结构性类型错误（string 收到 dict）→ INVALID_TYPE。"""
    d = tool_guard.begin("http_client", {"url": {"a": 1}})
    assert d is not None
    assert d["error_code"] == "INVALID_TYPE"


def test_unknown_key_allowed_with_warning(caplog):
    """一期策略：未知键仅告警放行（跑黄金集无误伤后再收紧）。"""
    import logging
    with caplog.at_level(logging.WARNING):
        d = tool_guard.begin(
            "search", {"query": "x", "totally_bogus_key": 1})
    assert d is None, "未知键一期不得拒绝"
    assert any("未知参数键" in r.message for r in caplog.records)


def test_path_escape_rejected():
    d = tool_guard.begin(
        "file_operations",
        {"operation": "write", "path": "/etc/passwd", "content": "x"})
    assert d is not None and d["error_code"] == "PATH_ESCAPE"

    d2 = tool_guard.begin(
        "file_operations",
        {"operation": "write", "path": "../escape.py", "content": "x"})
    assert d2 is not None and d2["error_code"] == "PATH_ESCAPE"

    # 批量形态的 files[].path 同样受约束
    d3 = tool_guard.begin(
        "file_operations",
        {"operation": "write",
         "files": [{"path": "../../x.py", "content": "x"}]})
    assert d3 is not None and d3["error_code"] == "PATH_ESCAPE"


def test_safe_url_rejected():
    d = tool_guard.begin("http_client", {"url": "file:///etc/passwd"})
    assert d is not None and d["error_code"] == "PATH_ESCAPE"
    assert tool_guard.begin("http_client", {"url": "https://x.com"}) is None


def test_consecutive_failure_circuit_breaker():
    """连续失败 ≥2 → 第 3 次 begin 拒（CONSECUTIVE_FAILURE）；成功清零。"""
    # 两轮真实 begin→finish 失败
    for i in range(2):
        assert tool_guard.begin("search", {"query": "q"}) is None
        tool_guard.finish("search", ok=False, detail=f"fail{i}")
    assert tool_guard.get_fail_count("search") == 2

    d = tool_guard.begin("search", {"query": "q"})
    assert d is not None
    assert d["error_code"] == "CONSECUTIVE_FAILURE"
    assert "换一种达成方式" in d["message"]

    # 成功一次后计数清零，恢复可调用
    tool_guard.finish("search", ok=True)
    assert tool_guard.get_fail_count("search") == 0
    assert tool_guard.begin("search", {"query": "q"}) is None


def test_approval_gate_deny_mode(monkeypatch):
    """APPROVAL_MODE=deny：write/exec/network 风险技能被拒，read 放行。"""
    monkeypatch.setattr(get_settings(), "tool_approval_mode", "deny")
    d = tool_guard.begin(
        "file_operations", {"operation": "read", "path": "a.py"})
    assert d is not None and d["error_code"] == "RISK_DENIED"

    d2 = tool_guard.begin("sandbox", {"code": "print(1)"})
    assert d2 is not None and d2["error_code"] == "RISK_DENIED"

    # read 级技能放行
    assert tool_guard.begin(
        "search_files", {"pattern": "foo"}) is None

    # 默认 auto 模式不拦
    monkeypatch.setattr(get_settings(), "tool_approval_mode", "auto")
    assert tool_guard.begin(
        "file_operations", {"operation": "read", "path": "a.py"}) is None


async def test_loader_integrates_guard():
    """loader.execute 挂载点：守卫拒绝 → SkillResult 带结构化 code。"""
    from app.agent.skills.core.progressive_loader import get_loader

    r = await get_loader().execute(
        "file_operations",
        {"operation": "write", "name": "x", "component": "y"})
    assert r.success is False
    assert r.error_code == "MISSING_PARAM"
    assert "参数结构异常" in (r.error or "")

    r2 = await get_loader().execute("ghost_skill", {})
    assert r2.success is False
    assert r2.error_code == "UNKNOWN_SKILL"


def test_audit_records_duration_and_timeout():
    """finish 记审计事件（duration_ms/error_code），供阶段六 JSONL 消费。"""
    assert tool_guard.begin("search", {"query": "q"}) is None
    tool_guard.finish("search", ok=False, detail="boom", error_code="EXEC_FAILED")
    events = [e for e in tool_guard.get_audit_events() if e["tool"] == "search"]
    assert len(events) == 1
    ev = events[0]
    assert ev["ok"] is False
    assert ev["error_code"] == "EXEC_FAILED"
    assert ev["detail"] == "boom"
    assert isinstance(ev["duration_ms"], (int, float))

    # 超时回执（main_graph._execute_with_timeout 调用形态）
    tool_guard.finish("sandbox", ok=False, detail="timeout 30s",
                      error_code="TIMEOUT")
    ev2 = tool_guard.get_audit_events()[-1]
    assert ev2["tool"] == "sandbox" and ev2["error_code"] == "TIMEOUT"
    assert tool_guard.get_fail_count("sandbox") == 1
