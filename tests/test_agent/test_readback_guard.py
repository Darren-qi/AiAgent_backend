"""写后读回跳过（规则13硬约束，TC-S15-06 行为面）。

背景（2026-11-13 用户反馈"避免反复读取"）：规则13 软引导三遍真跑里
两遍仍有"write 完立刻 read 同一批文件"的纯确认读——上执行层硬跳过：
上一动作是 write、本次 read 的文件全部在刚写列表里 → 不执行，
直接给跳过反馈（内容还在上下文），模型零成本继续推进。

合法读不受影响：读别的文件、或中间隔了 edit/execute 再读（依赖读）。
"""
from types import SimpleNamespace

import pytest

from app.agent.graphs.main_graph import AgentGraph


class _LoaderSpy:
    """记录 loader.execute 调用的假 loader。"""

    def __init__(self):
        self.calls = []

    async def execute(self, action, params):
        self.calls.append((action, dict(params)))
        return SimpleNamespace(metadata={}, success=True,
                               data={"ok": True}, error=None)


def _graph() -> AgentGraph:
    # 绕过重构造：执行路径只用到这几个属性
    g = AgentGraph.__new__(AgentGraph)
    g._session_id = "test_session"
    g._guard_prev_op = ""
    g._guard_last_write = set()
    g._readback_guard = {}
    return g


@pytest.mark.asyncio
async def test_read_after_write_same_files_is_skipped(monkeypatch):
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    w = {"action": "file_operations",
         "params": {"operation": "write",
                    "files": [{"path": "app/a.py", "content": "A"},
                              {"path": "app/b.py", "content": "B"}]}}
    r1 = {"action": "file_operations",
          "params": {"operation": "read", "path": "app/a.py"}}

    res_w = await g._execute_single_step(w, task_path="t1", session_id="s")
    assert res_w["success"] and len(spy.calls) == 1

    res_r = await g._execute_single_step(r1, task_path="t1", session_id="s")
    # 核心断言：写后读回不真执行
    assert len(spy.calls) == 1, f"写后读回仍执行了: {spy.calls}"
    assert res_r["success"], "跳过不算失败"
    assert res_r.get("data", {}).get("skipped") == "read_after_write"


@pytest.mark.asyncio
async def test_read_other_file_not_skipped(monkeypatch):
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    await g._execute_single_step(
        {"action": "file_operations",
         "params": {"operation": "write",
                    "files": [{"path": "app/a.py", "content": "A"}]}},
        task_path="t1", session_id="s")
    # 读没写过的文件 = 正常信息收集，必须执行
    res = await g._execute_single_step(
        {"action": "file_operations",
         "params": {"operation": "read", "path": "other/c.py"}},
        task_path="t1", session_id="s")
    assert len(spy.calls) == 2, "非读回 read 不应被跳过"
    assert res["success"]


@pytest.mark.asyncio
async def test_read_after_edit_not_skipped(monkeypatch):
    """中间隔了 edit（依赖读场景）→ 不是纯确认读，必须执行。"""
    spy = _LoaderSpy()
    monkeypatch.setattr(
        "app.agent.skills.core.progressive_loader.get_loader", lambda: spy)
    g = _graph()

    await g._execute_single_step(
        {"action": "file_operations",
         "params": {"operation": "write",
                    "files": [{"path": "app/models.py", "content": "M"}]}},
        task_path="t1", session_id="s")
    await g._execute_single_step(
        {"action": "file_operations",
         "params": {"operation": "edit", "path": "app/routes.py",
                    "edits": [{"old_text": "x", "new_text": "y"}]}},
        task_path="t1", session_id="s")
    # edit 后读刚写的 models.py（为改 routes 找字段）= 合法依赖读
    res = await g._execute_single_step(
        {"action": "file_operations",
         "params": {"operation": "read", "path": "app/models.py"}},
        task_path="t1", session_id="s")
    assert len(spy.calls) == 3, "edit 后的依赖读不应被跳过"
    assert res["success"]
