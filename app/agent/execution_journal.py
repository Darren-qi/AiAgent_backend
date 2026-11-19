"""
写操作意图日志（write-ahead journal）——崩溃后重试不重复副作用。

背景
    Agent 的执行断点是"事后"落盘的（每步执行完才 save_state）。进程在某个写操作
    执行到一半时崩溃，恢复后无法知道这一步做到哪，只能盲目重放；对
    sandbox 命令 / HTTP 请求 / 通知这类不可逆操作，盲目重放 = 重复扣款/重复发消息。

机制
    执行前先写一行 intent（status=running），执行后回写 done/failed。
    进程崩溃时残留 running 行，下一轮重入据此裁决：
        - 已生效（done / 世界状态核验通过）→ 直接返回上次结果，跳过重复执行
        - 未生效（核验明确不满足 / 上次 failed）→ 放行重执行
        - 无法确认（running 且无法核验）→ 返回 AMBIGUOUS_SIDE_EFFECT，交给模型先核验

语义三值（SKILL.md frontmatter `op_semantics` 声明，未声明一律按不可重放处理）
    idempotent  重放安全（读、整文件覆盖写）→ 根本不记 journal，零开销
    conditional 可用世界状态核验（move / delete / edit）→ running 时核验，已生效即复用
    once        不可重放（exec / network / 未声明）→ running 时返回 AMBIGUOUS_SIDE_EFFECT

失效策略
    所有 DB 操作失败一律 fail-open（降级为现状：无幂等保护，但不影响执行）。
    日志里有 WARNING，可观测。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update

logger = logging.getLogger(__name__)

# 语义三值
IDEMPOTENT = "idempotent"
CONDITIONAL = "conditional"
ONCE = "once"

# 'done' 只在这么短的时间内视为"同一次执行窗口"并抑制重放。
# 超过它说明是世界状态已变化后的新一轮调用（比如重跑 pytest），必须放行。
DONE_FRESH_SECONDS = 120

# 日志保留天数（时间兜底清理）
STALE_DAYS = 7
_PURGE_INTERVAL_SECONDS = 3600
_last_purge_ts = 0.0

# 决策动作
EXECUTE = "execute"      # 放行执行
REPLAY = "replay"        # 直接返回已记录结果，跳过执行
AMBIGUOUS = "ambiguous"  # 无法确认，返回 AMBIGUOUS_SIDE_EFFECT 交给模型核验


@dataclass
class JournalDecision:
    """open_journal 的裁决结果。"""

    action: str = EXECUTE
    op_key: str | None = None
    result: dict[str, Any] | None = None   # REPLAY 时返回给调用方的结果快照
    reason: str = ""

    @property
    def execute(self) -> bool:
        return self.action == EXECUTE


_AMBIGUOUS_MSG = (
    "该操作在上次崩溃前已发起，无法确认是否生效（{action}）。"
    "禁止原样重发：先核验结果（用 read/search_files 查文件、查接口返回），"
    "确认未生效再重做；确认已生效就直接继续下一步。"
)

_REPLAY_MSG = "该调用在上次崩溃前已成功执行过，已跳过重复执行（{action}）。"


def resolve_semantics(
    risk: str,
    retry: int,
    op_semantics: dict[str, str] | None,
    params: dict[str, Any],
) -> str:
    """按优先级解析一次调用的幂等语义。

    1. SKILL.md frontmatter `op_semantics[operation]`（开发者显式声明）
    2. `op_semantics["*"]`（该技能的兜底声明）
    3. `retry >= 1` —— 现有约定：幂等读类才配 retry>=1，写类默认 0
    4. `risk == read`
    5. 兜底 ONCE —— 无法确认就不重放（宁可让模型重规划，不可重复副作用）
    """
    op = str(params.get("operation") or "").strip().lower()
    table = op_semantics or {}
    if op and op in table:
        return table[op]
    if "*" in table:
        return table["*"]
    try:
        if int(retry or 0) >= 1:
            return IDEMPOTENT
    except (TypeError, ValueError):
        pass
    if (risk or "").strip().lower() == "read":
        return IDEMPOTENT
    return ONCE


def _normalize_params(params: dict[str, Any]) -> str:
    try:
        return json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - 序列化失败退化为 repr，不能挡住执行
        return repr(sorted((params or {}).items()))


# ---------------------------------------------------------- 落库参数脱敏
# 意图日志的 params 会进 action_journal.params（长期留存，运维可查）：
# http_client 的 headers（Authorization/Cookie）、notification 的收件人、
# sandbox 的 code 里都可能带密钥/PII。op_key 用**原始**参数算（重放匹配
# 不受影响），只有落库的副本做脱敏与截断。
_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word)?|secret|token|api[-_]?key|apikey|credential|"
    r"authorization|auth[-_]?header|private[-_]?key|session[-_]?key|"
    r"cookie|access[-_]?key|webhook[-_]?secret)",
    re.I,
)
_REDACTED = "***REDACTED***"
_MAX_STR_LEN = 1500      # 单个字符串截断（sandbox.code 这类可能很长）
_MAX_LIST_LEN = 100      # 列表最多留前 100 项
_MAX_DEPTH = 6           # 嵌套深度上限


def _redact_params(params: Any, _depth: int = 0) -> Any:
    """抹掉敏感键的值 + 截断超长内容（只影响落库副本，不影响 op_key）。"""
    if _depth > _MAX_DEPTH:
        return "..."
    if isinstance(params, dict):
        out: dict[str, Any] = {}
        for k, v in list(params.items())[:200]:
            key = str(k)
            out[key] = (
                _REDACTED if _SENSITIVE_KEY_RE.search(key)
                else _redact_params(v, _depth + 1)
            )
        return out
    if isinstance(params, (list, tuple)):
        return [_redact_params(v, _depth + 1) for v in list(params)[:_MAX_LIST_LEN]]
    if isinstance(params, str):
        return (params if len(params) <= _MAX_STR_LEN
                else params[:_MAX_STR_LEN] + f"...[+{len(params) - _MAX_STR_LEN} chars]")
    return params


def make_op_key(
    session_id: str,
    task_id: str | None,
    action: str,
    params: dict[str, Any],
) -> str:
    """意图键：同一会话+任务+技能+参数 → 同一个 key（唯一索引保证只有一行）。"""
    parts = [
        str(session_id or ""),
        str(task_id or ""),
        str(action or ""),
        _normalize_params(params or {}),
    ]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- DB I/O
# 全部 fail-open：journal 挂了不能挡住执行。

async def _load_row(op_key: str):
    from app.db.session import AsyncSessionLocal
    from app.models.action_journal import ActionJournal

    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(ActionJournal).where(ActionJournal.op_key == op_key)
        )
        return row.scalar_one_or_none()


async def _insert_running(
    op_key: str,
    session_id: str,
    task_id: str | None,
    todo_id: str | None,
    action: str,
    semantics: str,
    params: dict[str, Any],
) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.action_journal import ActionJournal

    async with AsyncSessionLocal() as session:
        session.add(ActionJournal(
            op_key=op_key,
            session_id=str(session_id or "")[:128],
            task_id=(str(task_id)[:128] if task_id else None),
            todo_id=(str(todo_id)[:64] if todo_id else None),
            action=str(action)[:50],
            semantics=semantics,
            params=_json_safe(_redact_params(params)),
            status="running",
        ))
        await session.commit()


async def _reset_running(op_key: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.action_journal import ActionJournal

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ActionJournal)
            .where(ActionJournal.op_key == op_key)
            .values(status="running", error=None, result=None)
        )
        await session.commit()


async def _update_status(
    op_key: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.action_journal import ActionJournal

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ActionJournal)
            .where(ActionJournal.op_key == op_key)
            .values(status=status, result=result, error=(str(error)[:4000] if error else None))
        )
        await session.commit()


async def purge_session(session_id: str) -> int:
    """任务成功收尾时清掉该会话的意图日志。"""
    if not session_id:
        return 0
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.action_journal import ActionJournal

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                delete(ActionJournal).where(ActionJournal.session_id == str(session_id))
            )
            await session.commit()
            return int(getattr(res, "rowcount", 0) or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("[Journal] purge_session(%s) 失败（不影响执行）: %s", session_id, e)
        return 0


async def _purge_stale() -> None:
    """按时间清理过期日志，进程内每小时最多跑一次。"""
    global _last_purge_ts
    now = time.monotonic()
    if now - _last_purge_ts < _PURGE_INTERVAL_SECONDS:
        return
    _last_purge_ts = now
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.action_journal import ActionJournal

        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(ActionJournal).where(ActionJournal.updated_at < cutoff)
            )
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("[Journal] 过期清理失败（不影响执行）: %s", e)


async def _maybe_verify(verify: Callable[[], Any] | None) -> bool | None:
    """跑技能提供的世界状态核验器，返回 True/False/None（无法判定）。"""
    if verify is None:
        return None
    try:
        value = verify()
        if inspect.isawaitable(value):
            value = await value
        if value is True:
            return True
        if value is False:
            return False
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[Journal] verify_replay 执行失败（按无法判定处理）: %s", e)
        return None


async def open_journal(
    *,
    action: str,
    params: dict[str, Any],
    session_id: str,
    task_id: str | None = None,
    todo_id: str | None = None,
    semantics: str = ONCE,
    verify: Callable[[], Any] | None = None,
) -> JournalDecision:
    """执行前裁决：放行 / 复用上次结果 / 返回无法确认。

    fail-open：任何 DB 异常 → 直接放行执行（退化为现状，无幂等保护）。
    """
    if semantics == IDEMPOTENT or not session_id:
        return JournalDecision(action=EXECUTE, reason="idempotent")

    op_key = make_op_key(session_id, task_id, action, params)
    try:
        await _purge_stale()
        row = await _load_row(op_key)

        # 从未记录 → 写 intent（write-ahead）
        if row is None:
            await _insert_running(
                op_key, session_id, task_id, todo_id, action, semantics, params
            )
            return JournalDecision(action=EXECUTE, op_key=op_key, reason="new")

        status = (row.status or "running").strip().lower()

        # conditional：永远以世界状态核验为准（核验是只读的，最可靠）
        if semantics == CONDITIONAL:
            verdict = await _maybe_verify(verify)
            if verdict is True:
                payload = _replay_payload(row, action)
                if payload.get("success") is not True:
                    # 核验已确认生效，但没有结果快照（崩溃发生在回写之前）
                    # —— 这正是核验要解决的主场景，不能退化成"无法确认"
                    payload = {
                        "success": True,
                        "data": {
                            "operation": "verified_replay",
                            "action": action,
                            "replayed": True,
                            "verified": True,
                        },
                        "message": _REPLAY_MSG.format(action=action),
                    }
                return JournalDecision(
                    action=REPLAY,
                    op_key=op_key,
                    result=payload,
                    reason="verify_applied",
                )
            if verdict is False:
                await _reset_running(op_key)
                return JournalDecision(
                    action=EXECUTE, op_key=op_key, reason="verify_not_applied"
                )
            # 无法核验 → 退化为按状态判定
            if status == "done" and _is_fresh(row):
                return JournalDecision(
                    action=REPLAY,
                    op_key=op_key,
                    result=_replay_payload(row, action),
                    reason="done_fresh",
                )
            if status == "failed":
                await _reset_running(op_key)
                return JournalDecision(action=EXECUTE, op_key=op_key, reason="retry_after_failed")
            if status == "ambiguous":
                # 已经把"无法确认"交回模型一次（mark_ambiguous 是我们自己写的），
                # 模型核验后仍原样重发 = 知情决定 → 放行，否则该操作永远卡死
                await _reset_running(op_key)
                return JournalDecision(action=EXECUTE, op_key=op_key,
                                       reason="adjudicated_retry")
            return _ambiguous(op_key, action, status)

        # once：不可重放
        if status == "done" and _is_fresh(row):
            return JournalDecision(
                action=REPLAY,
                op_key=op_key,
                result=_replay_payload(row, action),
                reason="done_fresh",
            )
        if status == "failed":
            # 上次明确失败 → 放行重试（这是常规路径，不放行会把任务卡死）
            await _reset_running(op_key)
            return JournalDecision(action=EXECUTE, op_key=op_key, reason="retry_after_failed")
        if status == "done":
            # 老的 done：世界状态多半已变化，放行（见 DONE_FRESH_SECONDS 注释）
            await _reset_running(op_key)
            return JournalDecision(action=EXECUTE, op_key=op_key, reason="stale_done")
        if status == "ambiguous":
            # 已经交回模型一次"无法确认"，模型核验后仍原样重发 = 知情决定 → 放行。
            # 否则一次性操作（exec/http/通知）会永远卡死：模型没法用世界状态核验
            # 一条命令有没有跑过，只能靠它自己判断后再决定重做。
            await _reset_running(op_key)
            return JournalDecision(action=EXECUTE, op_key=op_key,
                                   reason="adjudicated_retry")
        return _ambiguous(op_key, action, status)

    except Exception as e:  # noqa: BLE001 - fail-open
        logger.warning("[Journal] open_journal 失败（放行执行，无幂等保护）: %s", e)
        return JournalDecision(action=EXECUTE, op_key=None, reason=f"journal_error:{e}")


def _ambiguous(op_key: str, action: str, status: str) -> JournalDecision:
    return JournalDecision(
        action=AMBIGUOUS,
        op_key=op_key,
        result={
            "success": False,
            "error_code": "AMBIGUOUS_SIDE_EFFECT",
            "error": _AMBIGUOUS_MSG.format(action=action),
            "data": {"operation": "ambiguous", "action": action, "last_status": status},
        },
        reason=f"ambiguous:{status}",
    )


def _replay_payload(row: Any, action: str) -> dict[str, Any]:
    """把已记录的结果还原成一次执行返回。"""
    stored = row.result if isinstance(row.result, dict) else {}
    if stored.get("success") is True:
        data = stored.get("data")
        if isinstance(data, dict):
            data = {**data, "replayed": True}
        elif data is None:
            data = {"replayed": True}
        else:
            data = {"value": data, "replayed": True}
        return {
            "success": True,
            "data": data,
            "metadata": {"operation": "replay", "action": action},
            "message": _REPLAY_MSG.format(action=action),
        }
    # 没有可用的结果快照（老数据/写入失败）→ 只能当无法确认
    return {
        "success": False,
        "error_code": "AMBIGUOUS_SIDE_EFFECT",
        "error": _AMBIGUOUS_MSG.format(action=action),
        "data": {"operation": "ambiguous", "action": action, "last_status": "done"},
    }


def _json_safe(value: Any) -> Any:
    """JSON 列只收基本类型；不可序列化的退化成字符串，绝不挡执行。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except Exception:  # noqa: BLE001
        return str(value)


def snapshot_result(result: Any) -> dict[str, Any] | None:
    """把 SkillResult 压成可落 JSON 的结果快照（重放时原样还原）。"""
    if result is None:
        return None
    error = getattr(result, "error", None)
    return {
        "success": bool(getattr(result, "success", False)),
        "data": _json_safe(getattr(result, "data", None)),
        "error": (str(error)[:4000] if error else None),
    }


def _is_fresh(row: Any) -> bool:
    """该 done 行是否还在"同一次执行窗口"内。"""
    ts = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    if ts is None:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) <= timedelta(seconds=DONE_FRESH_SECONDS)


async def close_journal(
    op_key: str | None,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """执行结束回写（只有正常返回才调用；CancelledError 保持 running 作为崩溃证据）。"""
    if not op_key:
        return
    try:
        await _update_status(op_key, "done" if success else "failed",
                             result=result, error=error)
    except Exception as e:  # noqa: BLE001
        logger.warning("[Journal] close_journal(%s) 失败（不影响执行）: %s", op_key, e)


async def mark_ambiguous(op_key: str | None) -> None:
    """把残留行标成 ambiguous（已裁决为无法确认）。"""
    if not op_key:
        return
    try:
        await _update_status(op_key, "ambiguous")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Journal] mark_ambiguous 失败: %s", e)
