"""写操作意图日志（阶段八 P0）：崩溃后重试不重复副作用。

覆盖：
1. 语义解析优先级：op_semantics[op] → `*` → retry>=1 → risk=read → 兜底 once
2. file_operations SKILL.md 的语义声明契约（read/write 幂等、edit/delete 条件、create 一次性）
3. op_key 稳定性（参数一变 key 就变）
4. 决策树：新 op 放行 / done 新鲜窗口重放 / done 过期放行 / 残留 running → AMBIGUOUS
5. conditional 走世界状态核验：True 复用（无快照也给成功）、False 重跑、None 退化状态判定
6. idempotent 类不写库（零开销）
7. DB 故障 fail-open（日志挂了绝不能挡住执行）
8. loader 真实链路：崩溃残留 → 返回 AMBIGUOUS_SIDE_EFFECT 且不执行副作用
"""

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.agent import execution_journal as ej
from app.agent.execution_journal import (
    AMBIGUOUS,
    CONDITIONAL,
    DONE_FRESH_SECONDS,
    EXECUTE,
    IDEMPOTENT,
    ONCE,
    REPLAY,
    JournalDecision,
    close_journal,
    make_op_key,
    mark_ambiguous,
    open_journal,
    resolve_semantics,
    snapshot_result,
)

SESSION = "s_crash"
TASK = "t_crash"


# ------------------------------------------------------------------ 语义解析
class TestResolveSemantics:
    @pytest.mark.parametrize("params,semantics", [
        ({"operation": "read"}, IDEMPOTENT),      # 声明优先
        ({"operation": "edit"}, CONDITIONAL),
        ({"operation": "create"}, ONCE),
        ({"operation": "unknown_op"}, ONCE),      # 未声明 → 走下一级
        ({}, ONCE),                                # 无 operation → risk=write → once
    ])
    def test_file_operations_declared_table(self, params, semantics):
        """file_operations 声明表实际生效（真读 SKILL.md frontmatter）。"""
        text = Path("app/agent/skills/file_operations/SKILL.md").read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1])
        assert resolve_semantics(
            risk=fm.get("risk", ""), retry=int(fm.get("retry", 0) or 0),
            op_semantics=fm.get("op_semantics"), params=params,
        ) == semantics

    def test_star_fallback_beats_risk(self):
        assert resolve_semantics("write", 0, {"*": IDEMPOTENT}, {"operation": "x"}) == IDEMPOTENT

    def test_retry_ge_1_means_idempotent(self):
        assert resolve_semantics("network", 1, None, {}) == IDEMPOTENT

    def test_read_risk_means_idempotent(self):
        assert resolve_semantics("read", 0, None, {}) == IDEMPOTENT

    def test_write_without_declaration_is_once(self):
        """兜底必须是 once：拿不准就不重放（宁可让模型重规划）。"""
        assert resolve_semantics("write", 0, None, {"operation": "send"}) == ONCE
        assert resolve_semantics("exec", 0, None, {}) == ONCE


class TestOpKey:
    def test_stable_for_same_input(self):
        a = make_op_key(SESSION, TASK, "file_operations", {"operation": "delete", "path": "a.txt"})
        b = make_op_key(SESSION, TASK, "file_operations", {"path": "a.txt", "operation": "delete"})
        assert a == b, "参数顺序不同必须同 key"

    def test_changes_with_params_or_session(self):
        base = make_op_key(SESSION, TASK, "file_operations", {"operation": "delete", "path": "a.txt"})
        assert base != make_op_key(SESSION, TASK, "file_operations",
                                   {"operation": "delete", "path": "b.txt"})
        assert base != make_op_key("other", TASK, "file_operations",
                                   {"operation": "delete", "path": "a.txt"})
        assert base != make_op_key(SESSION, TASK, "sandbox", {"operation": "delete", "path": "a.txt"})


# ------------------------------------------------------------------ 内存打桩
class _Store:
    """把 execution_journal 的四个 DB helper 换成内存版（不碰真实 DB）。"""

    def __init__(self):
        self.rows = {}
        self.broken = False
        self.updates = []

    def _row(self, op_key, **kw):
        now = dt.datetime.now(dt.timezone.utc)
        base = dict(
            op_key=op_key, session_id=SESSION, task_id=TASK, todo_id="1",
            action="file_operations", semantics=ONCE, params={},
            status="running", result=None, error=None,
            created_at=now, updated_at=now)
        base.update(kw)
        return SimpleNamespace(**base)

    async def load(self, op_key):
        if self.broken:
            raise RuntimeError("db down")
        return self.rows.get(op_key)

    async def insert(self, op_key, session_id, task_id, todo_id, action, semantics, params):
        if self.broken:
            raise RuntimeError("db down")
        self.rows[op_key] = self._row(
            op_key, session_id=session_id, task_id=task_id, todo_id=todo_id,
            action=action, semantics=semantics, params=params)

    async def reset(self, op_key):
        self.rows[op_key].status = "running"

    async def update(self, op_key, status, result=None, error=None):
        row = self.rows[op_key]
        row.status = status
        row.result = result
        row.error = error
        row.updated_at = dt.datetime.now(dt.timezone.utc)
        self.updates.append((op_key, status))

    def seed(self, op_key, status, result=None, age_seconds=0, action="file_operations"):
        """预置一行（模拟上次崩溃前留下的痕迹）。"""
        row = self._row(op_key, action=action, status=status, result=result)
        row.updated_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age_seconds)
        self.rows[op_key] = row
        return row


async def _noop():
    return None


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(ej, "_load_row", s.load)
    monkeypatch.setattr(ej, "_insert_running", s.insert)
    monkeypatch.setattr(ej, "_reset_running", s.reset)
    monkeypatch.setattr(ej, "_update_status", s.update)
    monkeypatch.setattr(ej, "_purge_stale", _noop)
    return s


# ------------------------------------------------------------------ 决策树
class TestOpenJournal:
    @pytest.mark.asyncio
    async def test_new_op_writes_intent_and_executes(self, store):
        d = await open_journal(action="file_operations",
                               params={"operation": "delete", "path": "a.txt"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == EXECUTE and d.op_key
        assert store.rows[d.op_key].status == "running", "执行前必须先落 intent"

    @pytest.mark.asyncio
    async def test_idempotent_never_touches_db(self, store):
        d = await open_journal(action="file_operations",
                               params={"operation": "write", "path": "a.txt"},
                               session_id=SESSION, task_id=TASK, semantics=IDEMPOTENT)
        assert d.action == EXECUTE and d.op_key is None
        assert store.rows == {}, "幂等读写不记意图日志（零开销）"

    @pytest.mark.asyncio
    async def test_crash_residue_once_is_ambiguous(self, store):
        """崩溃后残留 running + 一次性操作 → 绝不重放，交模型核验。"""
        key = make_op_key(SESSION, TASK, "sandbox", {"command": "rm -rf out"})
        store.seed(key, "running", action="sandbox")
        d = await open_journal(action="sandbox", params={"command": "rm -rf out"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == AMBIGUOUS and d.op_key == key
        assert d.result["error_code"] == "AMBIGUOUS_SIDE_EFFECT"
        assert "核验" in d.result["error"]

        await mark_ambiguous(d.op_key)
        assert store.rows[key].status == "ambiguous"

        # 第二次重入（模型已看过"无法确认"）→ 放行，不会永久卡死
        d2 = await open_journal(action="sandbox", params={"command": "rm -rf out"},
                                session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d2.action == EXECUTE and d2.reason == "adjudicated_retry"

    @pytest.mark.asyncio
    async def test_ambiguous_residue_allows_informed_retry(self, store):
        """已交回模型一次"无法确认"后，模型核验完仍原样重发 = 知情决定 → 放行。

        （否则一次性操作永远卡死：模型无法用世界状态核验一条命令跑没跑过。）
        """
        key = make_op_key(SESSION, TASK, "sandbox", {"command": "deploy"})
        store.seed(key, "ambiguous", action="sandbox")
        d = await open_journal(action="sandbox", params={"command": "deploy"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == EXECUTE and d.reason == "adjudicated_retry"
        assert store.rows[key].status == "running", "重新打开 intent"

    @pytest.mark.asyncio
    async def test_failed_row_allows_retry(self, store):
        """上次明确失败 → 放行重试（不放行会把任务卡死）。"""
        key = make_op_key(SESSION, TASK, "sandbox", {"command": "pytest"})
        store.seed(key, "failed", action="sandbox")
        d = await open_journal(action="sandbox", params={"command": "pytest"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == EXECUTE and store.rows[key].status == "running"

    @pytest.mark.asyncio
    async def test_fresh_done_replays_stored_result(self, store):
        key = make_op_key(SESSION, TASK, "sandbox", {"command": "pytest"})
        store.seed(key, "done", result={"success": True, "data": {"code": 0}}, action="sandbox")
        d = await open_journal(action="sandbox", params={"command": "pytest"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == REPLAY
        assert d.result["success"] is True and d.result["data"]["code"] == 0
        assert d.result["data"]["replayed"] is True

    @pytest.mark.asyncio
    async def test_stale_done_executes_again(self, store):
        """超过新鲜窗口的老 done：世界状态可能已变，放行重跑（重跑 pytest 之类）。"""
        key = make_op_key(SESSION, TASK, "sandbox", {"command": "pytest"})
        store.seed(key, "done", result={"success": True},
                   age_seconds=DONE_FRESH_SECONDS + 60, action="sandbox")
        d = await open_journal(action="sandbox", params={"command": "pytest"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == EXECUTE and store.rows[key].status == "running"

    @pytest.mark.asyncio
    async def test_conditional_verify_applied_replays_without_snapshot(self, store):
        """核验说已生效 + 没有结果快照（崩溃在回写之前）→ 必须给成功，不能退回无法确认。"""
        key = make_op_key(SESSION, TASK, "file_operations",
                          {"operation": "edit", "path": "a.vue", "old": "x", "new": "y"})
        store.seed(key, "running", action="file_operations")  # 崩溃残留
        d = await open_journal(action="file_operations",
                               params={"operation": "edit", "path": "a.vue",
                                       "old": "x", "new": "y"},
                               session_id=SESSION, task_id=TASK,
                               semantics=CONDITIONAL, verify=lambda: True)
        assert d.action == REPLAY and d.reason == "verify_applied"
        assert d.result["success"] is True
        assert d.result["data"]["verified"] is True

    @pytest.mark.asyncio
    async def test_conditional_verify_not_applied_reexecutes(self, store):
        key = make_op_key(SESSION, TASK, "file_operations",
                          {"operation": "delete", "path": "a.txt"})
        store.seed(key, "running", action="file_operations")
        d = await open_journal(action="file_operations",
                               params={"operation": "delete", "path": "a.txt"},
                               session_id=SESSION, task_id=TASK,
                               semantics=CONDITIONAL, verify=lambda: False)
        assert d.action == EXECUTE and store.rows[key].status == "running"

    @pytest.mark.asyncio
    async def test_conditional_no_verifier_falls_back_to_status(self, store):
        key = make_op_key(SESSION, TASK, "file_operations",
                          {"operation": "move", "path": "a", "dest": "b"})
        store.seed(key, "running", action="file_operations")
        d = await open_journal(action="file_operations",
                               params={"operation": "move", "path": "a", "dest": "b"},
                               session_id=SESSION, task_id=TASK,
                               semantics=CONDITIONAL, verify=None)
        assert d.action == AMBIGUOUS

    @pytest.mark.asyncio
    async def test_no_session_id_skips_journal(self, store):
        d = await open_journal(action="sandbox", params={"command": "x"},
                               session_id="", semantics=ONCE)
        assert d.action == EXECUTE and store.rows == {}

    @pytest.mark.asyncio
    async def test_db_failure_fails_open(self, store):
        """journal 挂了必须放行执行，绝不拦。"""
        store.broken = True
        d = await open_journal(action="sandbox", params={"command": "x"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        assert d.action == EXECUTE and d.op_key is None
        assert d.reason.startswith("journal_error")

    @pytest.mark.asyncio
    async def test_close_journal_marks_done_and_failed(self, store):
        d = await open_journal(action="sandbox", params={"command": "x"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        await close_journal(d.op_key, success=True,
                            result=snapshot_result(SimpleNamespace(
                                success=True, data={"code": 0}, error=None)))
        assert store.rows[d.op_key].status == "done"
        assert store.rows[d.op_key].result["data"]["code"] == 0

        d2 = await open_journal(action="sandbox", params={"command": "y"},
                                session_id=SESSION, task_id=TASK, semantics=ONCE)
        await close_journal(d2.op_key, success=False, error="boom")
        assert store.rows[d2.op_key].status == "failed"
        assert store.rows[d2.op_key].error == "boom"

    @pytest.mark.asyncio
    async def test_close_journal_without_key_is_noop(self):
        await close_journal(None, success=True)   # 幂等类没有 key，不能抛

    @pytest.mark.asyncio
    async def test_cancelled_op_leaves_running(self, store):
        """CancelledError 路径不 close → 行保持 running（下一轮据此裁决）。"""
        d = await open_journal(action="sandbox", params={"command": "long"},
                               session_id=SESSION, task_id=TASK, semantics=ONCE)
        # 故意不调用 close_journal（模拟超时/取消/进程被杀）
        assert store.rows[d.op_key].status == "running"


class TestSnapshot:
    def test_snapshot_makes_json_safe(self):
        snap = snapshot_result(SimpleNamespace(
            success=True, data={"p": Path("/tmp/x"), "n": 3}, error=None))
        import json
        json.dumps(snap)  # 必须可序列化（JSON 列）
        assert snap["data"]["p"] == "/tmp/x" and snap["data"]["n"] == 3

    def test_snapshot_of_none(self):
        assert snapshot_result(None) is None

    def test_journal_decision_execute_property(self):
        assert JournalDecision(action=EXECUTE).execute is True
        assert JournalDecision(action=AMBIGUOUS).execute is False


# ------------------------------------------------------------------ loader 真实链路
class TestLoaderAmbiguousPath:
    """崩溃残留 → ProgressiveLoader 真实返回 AMBIGUOUS_SIDE_EFFECT 且不执行副作用。"""

    @staticmethod
    def _loader(monkeypatch):
        from app.agent.skills.core import progressive_loader as pl
        from app.agent.skills.guard import tool_guard

        monkeypatch.setattr(tool_guard, "begin", lambda *a, **k: None)
        monkeypatch.setattr(tool_guard, "finish", lambda *a, **k: None)

        async def _ambiguous_open(**kw):
            # 与真实 open_journal 同款裁决（DB 残留 running + 无核验器）
            return JournalDecision(action=AMBIGUOUS, op_key="op-key-crash", result={
                "success": False,
                "error_code": "AMBIGUOUS_SIDE_EFFECT",
                "error": "该操作在上次崩溃前已发起，无法确认是否生效（file_operations）。",
                "data": {"operation": "ambiguous", "last_status": "running"},
            }, reason="ambiguous:running")

        async def _mark(op_key):
            pass  # 不碰真实 DB

        monkeypatch.setattr(ej, "open_journal", _ambiguous_open)
        monkeypatch.setattr(ej, "mark_ambiguous", _mark)
        return pl.get_loader()

    @pytest.mark.asyncio
    async def test_ambiguous_returned_and_side_effect_skipped(self, monkeypatch, tmp_path):
        victim = tmp_path / "victim.txt"
        victim.write_text("keep me", encoding="utf-8")
        loader = self._loader(monkeypatch)

        params = {"operation": "delete", "path": "victim.txt",
                  "task_path": str(tmp_path), "session_id": SESSION,
                  "_op_ctx": {"session_id": SESSION, "task_id": TASK, "todo_id": "1"}}
        result = await loader.execute("file_operations", params)

        assert result.success is False
        assert result.error_code == "AMBIGUOUS_SIDE_EFFECT"
        assert victim.exists(), "无法确认时绝不能真去删（副作用必须被挡住）"
        assert "_op_ctx" not in params, "_op_ctx 必须被 loader 摘走，不进技能参数"


class TestParamsRedaction:
    """落库参数脱敏（2026-11-18 安全复查）：意图日志 params 不得带密钥/PII。"""

    def test_sensitive_keys_masked(self):
        params = {
            "url": "https://api.example.com/v1",
            "headers": {"Authorization": "Bearer sk-123", "X-Api-Key": "k"},
            "token": "t",
            "api_key": "k2",
            "password": "p",
            "content": "给运维的通知正文",
        }
        out = ej._redact_params(params)
        assert out["headers"]["Authorization"] == "***REDACTED***"
        assert out["headers"]["X-Api-Key"] == "***REDACTED***"
        assert out["token"] == out["api_key"] == out["password"] == "***REDACTED***"
        assert out["url"] == "https://api.example.com/v1", "非敏感值照常留存"
        assert out["content"] == "给运维的通知正文"

    def test_long_values_truncated(self):
        out = ej._redact_params({"code": "x" * 5000, "items": list(range(500))})
        assert len(out["code"]) < 5000 and out["code"].endswith("chars]")
        assert len(out["items"]) == 100

    def test_op_key_unaffected_by_redaction(self):
        """脱敏只动落库副本：op_key 必须按原始参数算，否则重放匹配会错位。"""
        p1 = {"headers": {"Authorization": "A"}}
        p2 = {"headers": {"Authorization": "B"}}
        assert ej._redact_params(p1) == ej._redact_params(p2), "脱敏后相同"
        assert ej.make_op_key(SESSION, TASK, "http_client", p1) != \
            ej.make_op_key(SESSION, TASK, "http_client", p2), "op_key 仍按原文区分"
