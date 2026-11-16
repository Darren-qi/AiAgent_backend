"""断点继续（TC-S16-03 配套，2026-11-14 用户定：截断续跑与失败收尾都支持断点继续）。

覆盖：
1. 失败收尾保留断点：note_failure + save/load 完整携带 failed_error 与未完成待办
2. cap_restore 对失败态：judge=继续 -> 复位 FAILED 待办续跑；judge=新任务 -> 丢弃
3. cap_restore 对截断态：judge=继续 -> 续预算（原行为回归）；新任务 -> 丢弃
4. 普通恢复态直通不惊动 judge（取消等既有语义不变）
5. 失败但全部待办已完成 = 无可续断点 -> 直接丢弃
"""

import pytest

from app.agent import roundcap_judge
from app.agent.execution_state import ExecutionStateManager, TodoStatus


def _sm_with_failed_state() -> ExecutionStateManager:
    """构造一个"失败收尾"后的断点状态（1完成 + 1失败，第5轮）。"""
    sm = ExecutionStateManager(session_id="s1", task_id="t1", user_input="改路由")
    sm.set_todos([
        {"id": "1", "title": "改 router/index.js", "action": "file_operations", "params": {}},
        {"id": "2", "title": "改 App.vue", "action": "file_operations", "params": {}},
    ])
    sm.todos[0].status = TodoStatus.COMPLETED
    sm.todos[1].status = TodoStatus.FAILED
    sm.todos[1].error = "缺少 path 参数"
    sm.current_todo_index = 1
    sm.iteration = 5
    sm.note_failure("1/2 个待办失败：任务未按要求完成")
    return sm


class _FakeSaver:
    """内存版 WorkingMemory 存取（契约同 PostgresSaver.save_working/get_working）。"""

    def __init__(self):
        self.store = {}

    async def save_working(self, session_id, memory_key, memory_value):
        self.store[(session_id, memory_key)] = memory_value
        return 1

    async def get_working(self, session_id, memory_key):
        v = self.store.get((session_id, memory_key))
        return {"value": v} if v is not None else None

    async def delete_working(self, session_id, memory_key):
        self.store.pop((session_id, memory_key), None)


class TestFailureCheckpoint:
    """失败收尾断点：落库与取回。"""

    @pytest.mark.asyncio
    async def test_note_failure_save_load_roundtrip(self):
        """失败收尾后状态行仍存在：failed_error + 未完成待办下一轮完整取回"""
        saver = _FakeSaver()
        sm = _sm_with_failed_state()
        sm._pg_saver = saver
        assert await sm.save_state(), "失败收尾必须能保存断点"

        sm2 = ExecutionStateManager(session_id="s1", task_id="t2", user_input="继续")
        sm2._pg_saver = saver
        assert await sm2.load_state(), "下一轮必须能取回断点"
        assert sm2.failed_error == "1/2 个待办失败：任务未按要求完成"
        assert sm2.todos[1].status == TodoStatus.FAILED
        assert sm2.todos[1].title == "改 App.vue"
        assert sm2.todos[0].status == TodoStatus.COMPLETED
        assert sm2.current_todo_index == 1
        assert "任务失败收尾" in sm2.scratchpad

    @pytest.mark.asyncio
    async def test_clear_state_still_works(self):
        """clear_state 语义保留（成功收尾/显式重置仍可清）"""
        saver = _FakeSaver()
        sm = _sm_with_failed_state()
        sm._pg_saver = saver
        await sm.save_state()
        assert await sm.clear_state()
        sm2 = ExecutionStateManager(session_id="s1", task_id="t3", user_input="x")
        sm2._pg_saver = saver
        assert not await sm2.load_state()

    def test_prepare_resume_resets_failed(self):
        """续跑前复位：FAILED 回 pending、失败标记被消费"""
        sm = _sm_with_failed_state()
        sm.prepare_resume()
        assert sm.todos[1].status == TodoStatus.PENDING
        assert sm.todos[1].error == ""
        assert sm.failed_error == ""
        assert not sm.is_all_todos_completed(), "复位后仍有待办，不能判全完成"


class TestCapRestoreFailedResume:
    """cap_restore 对"失败收尾"断点：续 / 弃。"""

    @pytest.mark.asyncio
    async def test_failed_continue_resumes(self, monkeypatch):
        async def _judge(task, prior):
            assert "任务失败收尾" in prior, "judge 必须看到失败上下文"
            return True

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = _sm_with_failed_state()
        sm2, restored = await roundcap_judge.cap_restore(sm, "继续", True)
        assert sm2 is sm and restored, "继续 -> 保留断点续跑"
        assert sm2.todos[1].status == TodoStatus.PENDING, "失败待办复位待重试"
        assert sm2.failed_error == ""
        assert sm2.max_iterations == 30, "非截断不续预算"

    @pytest.mark.asyncio
    async def test_failed_new_task_discards(self, monkeypatch):
        async def _judge(task, prior):
            return False

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = _sm_with_failed_state()
        sm2, restored = await roundcap_judge.cap_restore(sm, "做个新首页", True)
        assert sm2 is None and restored is False, "新任务 -> 丢弃断点"

    @pytest.mark.asyncio
    async def test_failed_all_completed_discards_without_judge(self, monkeypatch):
        async def _judge(task, prior):
            raise AssertionError("无可续断点不应惊动 judge")

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = ExecutionStateManager(session_id="s1", task_id="t1", user_input="x")
        sm.set_todos([{"id": "1", "title": "已完成的产出", "action": "file_operations", "params": {}}])
        sm.todos[0].status = TodoStatus.COMPLETED
        sm.note_failure("验收拒绝：产出不合格")
        sm2, restored = await roundcap_judge.cap_restore(sm, "继续", True)
        assert sm2 is None and restored is False


class TestCapRestoreTruncation:
    """cap_restore 对"30轮截断"断点：原行为回归。"""

    @staticmethod
    def _capped_sm() -> ExecutionStateManager:
        sm = ExecutionStateManager(session_id="s1", task_id="t1", user_input="x")
        sm.set_todos([
            {"id": "1", "title": "t1", "action": "file_operations", "params": {}},
            {"id": "2", "title": "t2", "action": "file_operations", "params": {}},
        ])
        sm.iteration = sm.max_iterations  # 预算用尽
        return sm

    @pytest.mark.asyncio
    async def test_truncated_continue_extends_budget(self, monkeypatch):
        async def _judge(task, prior):
            return True

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = self._capped_sm()
        budget_before = sm.max_iterations
        sm2, restored = await roundcap_judge.cap_restore(sm, "继续执行", True)
        assert sm2 is sm and restored
        assert sm2.max_iterations == sm2.iteration + sm2._round_window
        assert sm2.max_iterations > budget_before, "截断续跑必须续预算"

    @pytest.mark.asyncio
    async def test_truncated_new_task_discards(self, monkeypatch):
        async def _judge(task, prior):
            return False

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = self._capped_sm()
        sm2, restored = await roundcap_judge.cap_restore(sm, "开个新任务", True)
        assert sm2 is None and restored is False

    @pytest.mark.asyncio
    async def test_normal_restored_passthrough_not_judged(self, monkeypatch):
        """无失败无截断的恢复态（如用户取消后续话）：直通，不惊动 judge"""

        async def _judge(task, prior):
            raise AssertionError("普通恢复态不应调用 judge")

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = ExecutionStateManager(session_id="s1", task_id="t1", user_input="x")
        sm.set_todos([{"id": "1", "title": "t1", "action": "file_operations", "params": {}}])
        sm.iteration = 3
        sm2, restored = await roundcap_judge.cap_restore(sm, "继续", True)
        assert sm2 is sm and restored

    @pytest.mark.asyncio
    async def test_not_restored_passthrough(self, monkeypatch):
        async def _judge(task, prior):
            raise AssertionError("未恢复态不应调用 judge")

        monkeypatch.setattr(roundcap_judge, "judge_continue", _judge)
        sm = ExecutionStateManager(session_id="s1", task_id="t1", user_input="x")
        sm2, restored = await roundcap_judge.cap_restore(sm, "新任务", False)
        assert sm2 is sm and restored is False
