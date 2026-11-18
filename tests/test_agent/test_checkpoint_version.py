"""断点快照可靠性（阶段八 P1）：version 乐观锁 + 写失败上报。

覆盖：
1. save 写入 version 并递增；load 把 version 恢复成下一次的基线
2. save_state 必须真的把 expected_version 传给 saver（契约接线）
3. 并发覆盖（版本冲突）→ 采纳库里新基线重试一次 → 自愈，不算失败
4. 重试仍失败 → save_failures +1、回调 version_conflict（不再静默）
5. saver 抛异常 → 返回 False + 回调 save_failed（原来只 log）
6. 没挂回调也不能炸
7. 旧状态行没有 version 键 → 按 0 起步（向后兼容）
8. AgentGraph 侧的 SSE 上报通道 + 每轮最多 3 条（不刷屏）
"""

import pytest

from app.agent.execution_state import ExecutionStateManager


class CasSaver:
    """内存版 saver，带真实版本 CAS + 可注入故障。"""

    def __init__(self):
        self.store = {}
        self.save_calls = []
        self.raise_on_save = False
        self.conflict_times = 0  # 前 N 次 save 直接判冲突

    def _version(self, session_id, memory_key):
        v = self.store.get((session_id, memory_key))
        return int((v or {}).get("version", 0) or 0)

    async def save_working(self, session_id, memory_key, memory_value,
                           expected_version=None):
        self.save_calls.append(expected_version)
        if self.raise_on_save:
            raise RuntimeError("db down")
        if self.conflict_times > 0:
            self.conflict_times -= 1
            return 0
        if expected_version is not None and \
                self._version(session_id, memory_key) != expected_version:
            return 0
        self.store[(session_id, memory_key)] = memory_value
        return 1

    async def get_working(self, session_id, memory_key):
        v = self.store.get((session_id, memory_key))
        return {"value": v} if v is not None else None

    async def delete_working(self, session_id, memory_key):
        self.store.pop((session_id, memory_key), None)


def _sm(saver=None, session_id="s1"):
    sm = ExecutionStateManager(session_id=session_id, task_id="t1", user_input="改文件")
    sm.set_todos([{"id": "1", "title": "改 a.vue", "action": "file_operations", "params": {}}])
    if saver is not None:
        sm._pg_saver = saver
    return sm


class TestVersionLock:
    @pytest.mark.asyncio
    async def test_save_increments_and_load_restores(self):
        saver = CasSaver()
        sm = _sm(saver)
        assert await sm.save_state()
        assert sm._version == 1
        assert await sm.save_state()
        assert sm._version == 2

        sm2 = _sm(saver, session_id="s1")
        assert await sm2.load_state()
        assert sm2._version == 2, "load 必须恢复乐观锁基线，否则下一次 save 恒冲突"

    @pytest.mark.asyncio
    async def test_save_passes_expected_version(self):
        saver = CasSaver()
        sm = _sm(saver)
        await sm.save_state()
        await sm.save_state()
        assert saver.save_calls == [0, 1], "每次 save 都要带当时的 version 做 CAS"

    @pytest.mark.asyncio
    async def test_old_row_without_version_starts_at_zero(self):
        saver = CasSaver()
        saver.store[("s1", ExecutionStateManager._STATE_KEY)] = {"todos": [], "iteration": 3}
        sm = _sm(saver)
        assert await sm.load_state()
        assert sm._version == 0, "旧状态行（无 version 键）按 0 起步"
        assert await sm.save_state()
        assert sm._version == 1


class TestConflictRecovery:
    @pytest.mark.asyncio
    async def test_single_conflict_self_heals(self):
        """一次并发覆盖：采纳新基线重试成功 → 不算写失败。"""
        saver = CasSaver()
        sm = _sm(saver)
        await sm.save_state()          # version=1
        saver.conflict_times = 1        # 库里已被别人写到 version=5
        saver.store[("s1", ExecutionStateManager._STATE_KEY)]["version"] = 5

        reports = []
        sm.on_checkpoint_error = lambda reason, info: reports.append(reason)

        assert await sm.save_state(), "采纳新基线后必须能重试成功"
        assert sm._version == 6
        assert sm.save_failures == 0
        assert reports == [], "自愈不算失败，不该上报"
        assert sm.last_save_error == ""

    @pytest.mark.asyncio
    async def test_persistent_conflict_reports(self):
        """重试仍冲突 → 必须计数 + 上报（原来只 log，等于静默丢断点）。"""
        saver = CasSaver()
        sm = _sm(saver)
        await sm.save_state()
        saver.conflict_times = 99  # 永远冲突

        reports = []
        sm.on_checkpoint_error = lambda reason, info: reports.append((reason, info))

        assert not await sm.save_state()
        assert sm.save_failures == 1
        assert sm.last_save_error.startswith("version_conflict")
        assert reports and reports[0][0] == "version_conflict"
        assert "expected=" in reports[0][1]["detail"]


class TestSaveFailureReporting:
    @pytest.mark.asyncio
    async def test_exception_reports_save_failed(self):
        saver = CasSaver()
        saver.raise_on_save = True
        sm = _sm(saver)

        reports = []
        sm.on_checkpoint_error = lambda reason, info: reports.append(reason)

        assert not await sm.save_state(), "写失败必须返回 False"
        assert sm.save_failures == 1
        assert "db down" in sm.last_save_error
        assert reports == ["save_failed"]

    @pytest.mark.asyncio
    async def test_no_callback_does_not_raise(self):
        """回调没挂也必须安全（原来就只有 log，不能因为上报把保存搞崩）。"""
        saver = CasSaver()
        saver.raise_on_save = True
        sm = _sm(saver)
        assert not await sm.save_state()
        assert sm.save_failures == 1

    @pytest.mark.asyncio
    async def test_success_resets_nothing_and_saves_clean(self):
        saver = CasSaver()
        sm = _sm(saver)
        reports = []
        sm.on_checkpoint_error = lambda reason, info: reports.append(reason)
        assert await sm.save_state()
        assert sm.save_failures == 0 and reports == []


class TestGraphCheckpointEvent:
    """AgentGraph → SSE 的断点上报通道（每轮最多 3 条，前端未订阅即 no-op）。"""

    @staticmethod
    def _graph(events):
        from app.agent.graphs.main_graph import AgentGraph
        g = AgentGraph.__new__(AgentGraph)
        g._ckpt_on_step = lambda etype, payload: events.append((etype, payload))
        g._ckpt_fail_count = 0
        return g

    def test_reports_until_cap(self):
        events = []
        g = self._graph(events)
        for _ in range(5):
            g._report_checkpoint_error("save_failed", {"detail": "boom"})
        assert len(events) == 3, "断点故障会连续发生，必须限流"
        assert all(e[0] == "checkpoint_error" for e in events)
        assert events[0][1]["reason"] == "save_failed"
        assert events[0][1]["count"] == 1
        assert g._ckpt_fail_count == 5, "计数要全记（日志可见）"

    def test_count_increments_even_without_channel(self):
        events = []
        g = self._graph(events)
        g._ckpt_on_step = None
        g._report_checkpoint_error("save_failed", {"detail": "boom"})   # 不抛
        assert g._ckpt_fail_count == 1

    def test_callback_exception_does_not_break(self):
        def _boom(reason, info):
            raise RuntimeError("前端回调炸了")
        g = self._graph([])
        g._ckpt_on_step = _boom
        g._report_checkpoint_error("save_failed", {"detail": "x"})   # 不能向上抛


class TestPendingAction:
    """执行前 pending_action 写前快照（阶段八 P1）：崩溃时知道卡在哪一步。

    与 journal 的 running 行是互补的两层：journal 是 op 级（loader 登记），
    这里是 action 级，且不依赖 loader 是否登记成功 —— 派发前就落库。
    """

    @pytest.mark.asyncio
    async def test_roundtrip_through_snapshot(self):
        saver = CasSaver()
        sm = _sm(saver, session_id="sess1")
        sm.begin_pending_action("file_operations",
                                {"operation": "write", "path": "a.txt"})
        pa = sm.pending_action
        assert pa["action"] == "file_operations"
        assert len(pa["params_digest"]) == 8, "只存摘要，不存参数原文"
        assert await sm.save_state()

        sm2 = _sm(saver, session_id="sess1")
        assert await sm2.load_state()
        assert sm2.pending_action["action"] == "file_operations"
        assert sm2.pending_action["params_digest"] == pa["params_digest"]
        sm2.end_pending_action()
        assert sm2.pending_action is None

    @pytest.mark.asyncio
    async def test_prepare_resume_surfaces_breakpoint(self):
        sm = _sm(CasSaver())
        sm.begin_pending_action("sandbox", {"command": "deploy"})
        sm.prepare_resume()
        assert "【断点】上次中断时正在执行: sandbox" in sm.scratchpad
        assert sm.pending_action is None, "用完即清，否则每轮都重复刷"
        sm.prepare_resume()
        assert sm.scratchpad.count("【断点】") == 1

    @pytest.mark.asyncio
    async def test_step_writes_pending_before_dispatch(self, monkeypatch):
        """派发前落库：动作执行期间被杀，库里留着 pending_action。"""
        from types import SimpleNamespace

        from app.agent.graphs.main_graph import AgentGraph
        from app.agent.skills.core import progressive_loader as pl

        saver = CasSaver()
        sm = _sm(saver, session_id="sess1")
        g = AgentGraph.__new__(AgentGraph)
        g._state_manager = sm
        g._readback_guard = {}
        g._session_id = "sess1"
        g._task_id = "sess1"

        seen = {}

        class _Spy:
            async def execute(self, action, params):
                seen["during"] = dict(sm.pending_action or {})
                return SimpleNamespace(metadata={}, success=True,
                                       data={"ok": True}, error=None)

        monkeypatch.setattr(pl, "get_loader", lambda: _Spy())

        step = {"id": "1", "action": "file_operations",
                "params": {"operation": "read", "path": "a.txt"}}
        out = await g._execute_single_step(step, task_path="tasks/x",
                                           session_id="sess1")
        assert out["success"]

        assert seen["during"]["action"] == "file_operations", \
            "派发那一刻快照里必须带着'正在执行'"
        assert sm.pending_action is None, "动作收尾要清掉内存标记"
        stored = saver.store[("sess1", ExecutionStateManager._STATE_KEY)]
        assert stored["pending_action"]["action"] == "file_operations", \
            "写前落库：动作期间进程被杀，库里就有'卡在哪一步'的证据"
