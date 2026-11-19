"""JSONL run 日志（阶段六 Trace 最小闭环，2026-11-17）。

借鉴 AutoGen 后端 `logs/runs/`：一次 turn（execute 调用）一个文件
`logs/runs/{session_id}_{ts}.jsonl`，逐事件记录 llm_call / tool_call /
guard 拒绝，配合 DB（execution_nodes）与 app.log（含 model/latency）
构成"一次失败调用三处交叉定位"的三角。

铁律：
- 任何失败只降级不阻塞主流程（非关键路径失败只降级）；
- params 只存摘要（键名 + 序列化大小），不存全文（防日志爆炸）。
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 进程级状态：configure_run_log 在每个 turn 开始时重置
_state: dict[str, Any] = {"path": None, "session_id": None}


def configure_run_log(session_id: str | None) -> None:
    """turn 开始时调用：打开本 turn 的 run 日志文件。

    session_id 为空（单测/无会话）→ 禁用落盘，run_log 变 no-op。
    """
    if not session_id:
        _state["path"] = None
        _state["session_id"] = None
        return
    try:
        # app/agent/trace.py → parents[2] = 仓库根
        runs_dir = Path(__file__).resolve().parents[2] / "logs" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        _state["path"] = runs_dir / f"{session_id}_{ts}.jsonl"
        _state["session_id"] = str(session_id)
    except Exception as e:  # noqa: BLE001 - 降级为不落盘
        logger.warning("[Trace] run 日志初始化失败（降级不落盘）: %s", e)
        _state["path"] = None


def get_run_log_path() -> Path | None:
    """当前 turn 的 run 日志路径（未启用返回 None）。测试/排障用。"""
    return _state.get("path")


def run_log(event: str, **fields: Any) -> None:
    """追加一条事件。未 configure 或写入失败都只降级，绝不阻塞。"""
    path = _state.get("path")
    if not path:
        return
    try:
        from app.middleware.request_id import get_request_id
        rec = {
            "ts": round(time.time(), 3),
            "event": event,
            "request_id": get_request_id() or None,
        }
        rec.update(fields)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Trace] run 日志写入失败（忽略）: %s", e)


def params_digest(params: Any) -> dict[str, Any]:
    """params 摘要：只存键名列表与序列化大小，不存全文。"""
    try:
        if isinstance(params, dict):
            keys = sorted(str(k) for k in params)[:20]
        else:
            keys = []
        raw = json.dumps(params, ensure_ascii=False, default=str) \
            if params is not None else ""
        return {"keys": keys, "size": len(raw)}
    except Exception:  # noqa: BLE001
        return {"keys": [], "size": -1}
