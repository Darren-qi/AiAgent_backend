"""ToolGuard —— 工具执行前守卫检查点（阶段三，2026-11-17）。

蓝本：AutoGen 后端 `security/authorizer.py`（RunGuard 三件套），适配而非照搬
（LG 技能是 SKILL.md + 文本协议，不迁 @tool 形态）。与 progressive_loader
现有 L5 参数闸门合并为**单一检查点**：不通过不进 skill。

begin() 顺序（计划 tool-harness-upgrade.md §阶段三）：
  1. 注册表白名单      未注册 → UNKNOWN_SKILL
  2. 结构化 schema 校验  operation_targets 契约（必填）+ parameters 类型检查
                        → MISSING_PARAM / INVALID_TYPE（未知键一期仅 warning）
  3. 参数级约束        safe_path / safe_url 收口 → PATH_ESCAPE
  4. 工具级连续失败熔断  连续失败 ≥ limit 拒下一次 → CONSECUTIVE_FAILURE
  5. 风险门            risk∈{write,exec,network} 且 APPROVAL_MODE=deny → RISK_DENIED

finish() 更新失败计数 + 记审计事件（event/tool/ok/detail/duration_ms，
阶段六 JSONL run 日志消费）。返回结构化拒绝 dict，模型直接可读。
"""

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 路径逃逸黑名单前缀（系统敏感目录；任务目录内相对路径不受影响）
_ABS_BLOCK_PREFIXES = (
    "/etc", "/usr", "/bin", "/sbin", "/System", "/Library",
    "/proc", "/sys", "/dev", "/root", "/private",
)
# URL 允许的协议（safe_url 收口）
_URL_SCHEMES = ("http://", "https://")
# 未知键告警时忽略的注入键（main_graph 统一回填，非模型输出）
_INJECTED_KEYS = ("task_path", "session_id", "project_name")


def _deny(code: str, message: str) -> Dict[str, str]:
    """结构化拒绝（对齐 AutoGen _deny 形态，模型直接可读）。"""
    return {
        "denied": True,
        "error_code": code,
        "message": f"[{code}] {message}（工具层守卫拦截，未执行）",
    }


def _collect_paths(params: Dict[str, Any], path_arg: str) -> list:
    """收集本次调用涉及的所有路径值（path_arg + 批量键 + dest）。"""
    vals = []
    if path_arg and isinstance(params.get(path_arg), str):
        vals.append(params[path_arg])
    for key in ("files", "edits", "paths"):
        v = params.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    vals.append(item["path"])
                elif isinstance(item, str):
                    vals.append(item)
    if isinstance(params.get("dest"), str):
        vals.append(params["dest"])
    if isinstance(params.get("from"), str):
        vals.append(params["from"])
    return vals


def _check_paths(params: Dict[str, Any], path_arg: str) -> Optional[Dict[str, str]]:
    """路径约束：`..` 上跳与系统敏感绝对路径 → PATH_ESCAPE。"""
    for p in _collect_paths(params, path_arg):
        parts = Path(p).parts
        if ".." in parts:
            return _deny(
                "PATH_ESCAPE",
                f"路径含 '..' 上跳（{p}），禁止逃出任务目录；"
                "只写任务目录内的相对路径",
            )
        if p.startswith("/") and p.startswith(_ABS_BLOCK_PREFIXES):
            return _deny(
                "PATH_ESCAPE",
                f"禁止访问系统路径 {p}；只能操作任务目录内的相对路径",
            )
    return None


def _check_url(url: str) -> Optional[Dict[str, str]]:
    """safe_url 收口：仅允许 http/https（file:// 等协议拒绝）。"""
    u = url.strip().lower()
    if not u.startswith(_URL_SCHEMES):
        return _deny(
            "PATH_ESCAPE",
            f"URL 协议非法（{url[:80]}）；只允许 http:// 或 https://",
        )
    return None


def _check_types(meta: Any, params: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """参数类型检查（stdlib 手写，不引 jsonschema）。

    保守策略（防误伤，计划 §风险表）：只拦结构性错误——
    object/array 声明收到标量、string 声明收到 dict/list；
    数字字符串等可 coerce 形态放行。未知键仅 warning 不拦（一期）。
    """
    props = ((meta.parameters or {}).get("properties")) or {}
    if not props:
        return None
    for key, value in params.items():
        if value is None or key in _INJECTED_KEYS:
            continue
        spec = props.get(key)
        if spec is None:
            logger.warning(
                "[ToolGuard] 未知参数键 skill=%s key=%s（一期仅告警放行）",
                meta.name, key)
            continue
        declared_raw = spec.get("type")
        # 支持联合类型（如 input_data: [string, object, array]——技能直通 dict）
        declared_list = (
            [str(t).lower() for t in declared_raw]
            if isinstance(declared_raw, list)
            else [str(declared_raw).lower()] if declared_raw else []
        )
        if not declared_list:
            continue
        if not any(_matches_type(t, value) for t in declared_list):
            return _deny(
                "INVALID_TYPE",
                f"参数 {key} 类型不符（声明 {declared_raw}，"
                f"收到 {type(value).__name__}）"
                + ("——参数结构疑似崩坏"
                   if isinstance(value, (dict, list)) and "string" in declared_list
                   else ""),
            )
    return None


def _matches_type(declared: str, value: Any) -> bool:
    """单类型匹配（保守：结构性错误才判 False，可 coerce 形态放行）。"""
    if declared in ("object", "dict"):
        # dict/list 都算结构化承载（个别技能用数组承载结构化参数）
        return isinstance(value, (dict, list))
    if declared == "array":
        return isinstance(value, list)
    if declared == "string":
        # 字符串声明收到 dict/list = 结构崩坏（TC-S16-04 形态）
        return isinstance(value, str)
    if declared in ("number", "integer"):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        # 数字字符串放行（LLM 常把 5 写成 "5"）
        return isinstance(value, str) and value.strip() != ""
    if declared == "boolean":
        if isinstance(value, bool):
            return True
        # 非结构化值放行（避免误伤 "true" 字符串）
        return not isinstance(value, (dict, list))
    return True  # 未识别类型不拦


class ToolGuard:
    """执行前守卫 + 失败熔断 + 审计（进程内单例 tool_guard）。"""

    def __init__(self, audit_limit: int = 1000):
        self._fail_counts: Dict[str, int] = {}
        self._start_times: Dict[str, float] = {}
        # 审计事件环形缓冲（阶段六 JSONL run 日志消费）
        self._audit: deque = deque(maxlen=audit_limit)

    # ---------- 执行前检查点 ----------

    def begin(self, name: str, params: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """执行前守卫。返回 None=放行；dict=结构化拒绝（不进 skill）。"""
        from app.agent.skills.core.progressive_loader import (
            classify_params_problem,
            get_loader,
            validate_params_structure,
        )

        # 1. 注册表白名单
        meta = get_loader().get_guard_meta(name)
        if meta is None:
            return _deny(
                "UNKNOWN_SKILL",
                f"技能 '{name}' 未注册；只能使用可用工具列表中的动作名",
            )

        # 2. 结构化校验：operation_targets 契约（必填）+ 类型
        #    （params 非 dict / 缺目标参数 → validate 已覆盖）
        prob = validate_params_structure(name, params)
        if prob:
            code = classify_params_problem(prob)
            # 保留"参数结构异常"文案（TC-S16-04 测试契约），前缀补 code
            return {
                "denied": True,
                "error_code": code,
                "message": f"[{code}] {prob}（参数结构异常，未执行）",
            }
        type_deny = _check_types(_MetaShim(meta), params)
        if type_deny:
            return type_deny

        # 3. 参数级约束（safe_path / safe_url 收口）
        path_deny = _check_paths(params, meta.get("path_arg") or "")
        if path_deny:
            return path_deny
        url_arg = meta.get("url_arg") or ""
        if url_arg and isinstance(params.get(url_arg), str) and params[url_arg]:
            url_deny = _check_url(params[url_arg])
            if url_deny:
                return url_deny

        # 4. 工具级连续失败熔断（与调用级同 call_key≥3 并存互补）
        from app.core.config import get_settings
        limit = get_settings().tool_consecutive_fail_limit
        fails = self._fail_counts.get(name, 0)
        if limit > 0 and fails >= limit:
            return _deny(
                "CONSECUTIVE_FAILURE",
                f"工具 {name} 已连续失败 {fails} 次被熔断；"
                "请换一种达成方式，或向用户报告障碍后停止重试",
            )

        # 5. 风险门（一期默认 auto 留钩；deny 拒绝 write/exec/network）
        if get_settings().tool_approval_mode == "deny" and meta.get("risk") in (
            "write", "exec", "network"
        ):
            return _deny(
                "RISK_DENIED",
                f"当前审批模式禁止 {meta.get('risk')} 风险级工具 {name}",
            )

        self._start_times[name] = time.perf_counter()
        return None

    def finish(
        self,
        name: str,
        ok: bool,
        detail: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> None:
        """执行结果回执：更新熔断计数 + 记审计事件。

        ok=True 清零连续失败；ok=False 累加。用户取消不经此路（不计失败）。
        """
        duration_ms = None
        started = self._start_times.pop(name, None)
        if started is not None:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)

        if ok:
            self._fail_counts[name] = 0
        else:
            self._fail_counts[name] = self._fail_counts.get(name, 0) + 1

        self._audit.append({
            "event": "tool_call",
            "tool": name,
            "ok": ok,
            "error_code": error_code,
            "detail": (str(detail)[:300] if detail else None),
            "duration_ms": duration_ms,
            "ts": time.time(),
        })

    # ---------- 观测接口 ----------

    def get_fail_count(self, name: str) -> int:
        return self._fail_counts.get(name, 0)

    def get_audit_events(self) -> list:
        """审计事件快照（阶段六 JSONL run 日志消费）。"""
        return list(self._audit)

    def reset(self) -> None:
        """清空熔断计数与审计（测试/管理端用）。"""
        self._fail_counts.clear()
        self._start_times.clear()
        self._audit.clear()


class _MetaShim:
    """get_guard_meta dict → _check_types 期望的属性访问形态。"""

    def __init__(self, meta: Dict[str, Any]):
        self.name = meta.get("name", "")
        self.parameters = meta.get("parameters") or {}


# 进程内单例（loader.execute 挂载点消费）
tool_guard = ToolGuard()
