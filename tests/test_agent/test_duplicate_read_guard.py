"""重复读跳过（生产 2026-11-14 00:12 第三轮空转复现，TC-S7-07）。

现场：session_1794585775850 第3轮 todo1（挂载 TasksView）5 轮预算内
连发 5 次 read（router/index.js×3、App.vue×2），零写改 →
"达到最大循环次数" → 1/1 待办失败 → 任务失败收尾。

修复：同 turn 内同文件第 2 次 read 起直接跳过（内容已在上下文），
反馈"必须直接 edit/write"，并照失败退轮模式退还 1 轮预算。
ReadbackGuard 的 read_files 按 turn 清空——跨 turn（新对话轮）上下文
是摘要，首读不能跳（否则误伤真需要读的场景）。
"""
from types import SimpleNamespace

import pytest

from app.agent.graphs.main_graph import AgentGraph


class _LoaderSpy:
    def __init__(self):
        self.calls = []

    async def execute(self, action, params):
        params.pop("_op_ctx", None)  # 真 loader 会摘走（阶段八意图日志）
        self.calls.append((action, dict(params)))
        return SimpleNamespace(metadata={}, success=True,
                               data={"ok": True}, error=None)


def _graph() -> AgentGraph:
    g = AgentGraph.__new__(AgentGraph)
    g._session_id = "test_session"
    g._readback_guard = {}
    g._task_id = None  # 执行前注入 _op_ctx 要读（真实对象由 __init__ 提供）
    return g


def _read(path):
    return {"action": "file_operations",
            "params": {"operation": "read", "path": path}}


@pytest.mark.asyncio
async def test_duplicate_read_same_file_is_skipped(monkeypatch):
    """同 turn 同文件第 2 次 read → 跳过（生产第三轮空转的直接掐断）。"""
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    r1 = await g._execute_single_step(_read("frontend/src/router/index.js"),
                                      task_path="t", session_id="s")
    assert r1["success"] and len(spy.calls) == 1

    r2 = await g._execute_single_step(_read("frontend/src/router/index.js"),
                                      task_path="t", session_id="s")
    assert len(spy.calls) == 1, f"重复读仍执行了: {spy.calls}"
    assert r2["success"], "跳过不算失败"
    assert r2.get("data", {}).get("skipped") == "duplicate_read"
    # 反馈必须带行动指令，把模型从"再看看"里拽出来
    assert "edit" in r2["data"]["message"] or "写" in r2["data"]["message"]


@pytest.mark.asyncio
async def test_read_other_file_still_executes(monkeypatch):
    """没读过的文件照常读（不误伤首次信息收集）。"""
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    await g._execute_single_step(_read("a.py"), task_path="t", session_id="s")
    await g._execute_single_step(_read("b.py"), task_path="t", session_id="s")
    assert len(spy.calls) == 2


@pytest.mark.asyncio
async def test_turn_reset_clears_read_files(monkeypatch):
    """新对话轮（turn）必须清空已读集合：跨 turn 上下文是摘要，
    再读是合法首读（生产第三轮正是新 turn 读 App.vue）。"""
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    await g._execute_single_step(_read("App.vue"), task_path="t", session_id="s")
    g._reset_readback_turn("s")
    r = await g._execute_single_step(_read("App.vue"), task_path="t",
                                     session_id="s")
    assert len(spy.calls) == 2, "turn 重置后首读应正常执行"
    assert r["success"]


def test_loop_refunds_skip_in_source():
    """循环层：跳过轮退1轮预算（源码断言，循环层太重跑不动）——
    没有退轮，跳过只是省执行时间，5 轮预算照样烧光判失败。"""
    from pathlib import Path
    src = (Path(__file__).parents[2] / "app/agent/graphs/main_graph.py"
           ).read_text(encoding="utf-8")
    assert "_skip_refunds" in src
    assert "跳过不产进展却烧预算" in src
