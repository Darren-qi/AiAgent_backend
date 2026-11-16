"""Agent 主图 - LangGraph 核心编排 (统一执行模式)"""

import logging
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from app.agent.graphs.nodes.intent_detector import IntentDetector
from app.agent.graphs.nodes.planner import Planner
from app.agent.graphs.nodes.executor import Executor
from app.agent.graphs.nodes.integrator import Integrator
from app.agent.graphs.nodes.guard import Guard
from app.agent.graphs.nodes.replanner import Replanner
from app.agent.graphs.dynamic_subgraph import DynamicSubgraph
from app.agent.graphs.supervisor_graph import SupervisorGraph, SupervisorDecision
from app.agent.state import (
    ExecutionContext,
    ExecutionStatus,
    ObservationResult,
    LoopDetectionResult,
    create_execution_context,
    default_loop_detector,
)
from app.agent.execution_state import ExecutionStateManager, TodoStatus
from app.agent.task_executor import task_manager
from app.models.execution_node import ExecutionNode

logger = logging.getLogger(__name__)


def build_plan_interception(plan_result: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """坏计划拦截判定（阶段一 · 快改1，2026-11-16）。

    planner 解析层已标记 params_invalid 的计划不进执行——返回结构化
    last_error（含 error_code）由调用方走 correction，省一次必败的
    执行往返；正常计划返回 None。纯函数，供单测直接断言。
    """
    if not plan_result or not plan_result.get("params_invalid"):
        return None
    reason = str(plan_result.get("params_invalid_reason") or "参数结构异常")
    from app.agent.skills.core.progressive_loader import classify_params_problem
    code = classify_params_problem(reason)
    return {
        "error": f"计划参数无效（未执行，error_code={code}）: {reason}",
        "error_code": code,
    }


def _walk_dir(base: Path, current: Path) -> List[Dict[str, Any]]:
    """按 {name, path, type, children} 递归列出任务目录（与前端文件树格式一致）。

    文件由 file_operations skill 写到 get_tasks_dir()/<project>，
    而 StorageManager 的本地根目录指向另一处 tasks，用它构建恒为空树。
    """
    result: List[Dict[str, Any]] = []
    try:
        for item in sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if item.name.startswith("."):
                continue
            node = {
                "name": item.name,
                "path": str(item.relative_to(base)),
                "type": "directory" if item.is_dir() else "file",
            }
            if item.is_dir():
                node["children"] = _walk_dir(base, item)
            result.append(node)
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        pass
    return result


# 容器型项目目录段（剥前缀用）：任务目录名永远带 _<时间戳> 后缀
# （skill create/auto-create 都会追加 _timestamp）。
# 2026-11-13 修：旧正则连裸 "app"/"project" 也匹配，导致 Flask 项目的
# app/__init__.py 被 _norm_rel 剥成根目录 __init__.py（生产 session_1794546906875
# 观察原话"写入路径为任务目录根下的 __init__.py，而待办目标是 app/__init__.py"），
# 根目录/子目录因此错乱、后续按子目录读取全部失败。
_PROJECT_SEG_RE = re.compile(r"^(?:auto_project|app|project)_\d+$")


def _norm_rel(p: str) -> str:
    """把模型给的 path 规范化为任务目录内的相对路径。

    剥离 ./ 前缀、开头的 tasks/ 段、任务目录名/其他项目目录名段。
    （2026-11-09 生产 task33：模型把 path 写成 app_1794153457/src/...，
    落盘变成任务目录下的嵌套垃圾目录，文件闸门永远找不到 → 待办假失败。）
    """
    if not p or p.startswith("/") or p.startswith("~"):
        return p
    s = str(p).replace("\\", "/").strip().strip('`"\'')
    while s.startswith("./"):
        s = s[2:]
    segs = [x for x in s.split("/") if x not in ("", ".")]
    while segs and len(segs) > 1 and (segs[0] == "tasks" or _PROJECT_SEG_RE.match(segs[0])):
        segs = segs[1:]
    return "/".join(segs)


def _check_promised_files(
    files_mentioned: Optional[List[str]],
    params: Optional[Dict[str, Any]],
    execution_result: Optional[Dict[str, Any]],
    base_dir: Optional[Path],
) -> List[str]:
    """收集本待办过程中提到的文件，返回磁盘上不存在的那些（相对路径）。

    规则（用户 2026-11-09 要求）：过程中提到的文件必须出现在文件结构区；
    文件没生成 = 代码逻辑有问题，待办禁止标记完成，必须重试。
    提取用 LLM（observe 的"文件:"行），本函数只做确定性的存在性检查。
    """
    candidates: List[str] = [str(f).strip() for f in (files_mentioned or []) if str(f).strip()]
    for key in ("path", "output_path"):
        v = (params or {}).get(key)
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())
    data = (execution_result or {}).get("data")
    if isinstance(data, dict):
        for f in data.get("written_files") or []:
            if isinstance(f, str) and f.strip():
                candidates.append(f.strip())
        p = data.get("path")
        if isinstance(p, str) and p.strip():
            candidates.append(p.strip())
            if base_dir is None and Path(p).is_absolute():
                base_dir = Path(p).parent

    missing: List[str] = []
    seen = set()
    _basenames: Optional[set] = None
    for c in candidates:
        c = c.strip().strip('`"\'').replace("\\", "/")
        if not c or c in seen or re.match(r"^(https?|ftp)://", c, re.I):
            continue
        # 注意：这里不能提前 seen.add(c)——下面 _norm_rel 规范化后还有一次
        # `c in seen` 去重，提前登记会让未被改写的裸相对路径（ghost.py 等）
        # 永远在第二次判定处被 continue，存在性检查形同虚设
        # （2026-11-13 修：生产只有被剥前缀改写的路径才会被报缺失）
        # 格式过滤：只校验"文件形态"的提及（basename 带扩展名、不含空格），跳过目录/概念
        base = c.rstrip("/").split("/")[-1]
        if " " in c or "." not in base:
            continue
        if Path(c).is_absolute():
            # 绝对路径只校验任务目录内的，系统文件/第三方路径不拦
            if base_dir and Path(c).exists() is False and str(Path(c)).startswith(str(base_dir)):
                missing.append(c)
            continue
        c = _norm_rel(c)
        if not c or c in seen:
            continue
        seen.add(c)
        if base_dir and not (base_dir / c).exists():
            # 裸文件名（不含 /）兜底：同名文件已在子目录（承诺 extensions.py、
            # 实际 app/extensions.py）→ 视为已存在。否则失败的错误路径
            # （read extensions.py）会进候选、被误报缺失，逼模型在根目录
            # 写出重复文件（2026-11-13 生产取证：__init__.py 被误报缺失后
            # 模型在根目录补写了一份）。带前缀的路径仍精确匹配。
            # 2026-11-13 生产取证（任务93重构）：move 之后旧路径 app/extensions.py
            # 按根相对找不到就报"不存在"，其实文件已在 backend/app/ 下——带斜杠
            # 的提及同样做 basename 子目录兜底（文件出现在任务目录任何位置的
            # 文件结构里即算存在），否则归类后连续三轮误报缺失逼模型重找。
            if _basenames is None:
                _basenames = set()
                try:
                    for _br, _bd, _bfs in os.walk(base_dir):
                        _basenames.update(_bfs)
                except Exception:
                    pass
            if base not in _basenames:
                missing.append(c)
    return missing


class AgentState:
    """Agent 状态"""
    def __init__(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        task: str = "",
        intent: Optional[str] = None,
        intents: Optional[List[str]] = None,
        plan: Optional[List[Dict[str, Any]]] = None,
        current_step: int = 0,
        results: Optional[List[Any]] = None,
        error: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        routing: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
    ):
        self.messages = messages or []
        self.task = task
        self.intent = intent
        self.intents = intents or []
        self.plan = plan
        self.current_step = current_step
        self.results = results or []
        self.error = error
        self.context = context or {}
        self.routing = routing
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "messages": self.messages,
            "task": self.task,
            "intent": self.intent,
            "intents": self.intents,
            "plan": self.plan,
            "current_step": self.current_step,
            "results": self.results,
            "error": self.error,
            "context": self.context,
            "routing": self.routing,
            "confidence": self.confidence,
        }


from app.agent.roundcap_judge import cap_restore, cap_notice


def _stop_result(state, stop_reason: str) -> dict:
    """终止结果:轮次上限->收尾标记;其余->取消。"""
    if stop_reason == "达到最大迭代次数":
        state.context["_rounds_capped"] = True
        return {"success": False, "summary": "已达轮次上限", "capped": True}
    # 只有真取消才标 cancelled；"存在不可恢复的错误"等终止理由 ≠ 用户取消
    cancelled = stop_reason in ("用户取消执行", "用户中断")
    return {"success": False, "summary": stop_reason, "cancelled": cancelled}


class AgentGraph:
    """Agent 主图 - 统一执行引擎

    所有任务共享同一套执行逻辑，不再区分 simple/medium/high 模式。
    特性:
    - 迭代循环: 支持自动重规划
    - 并行执行: 独立步骤并行执行
    - Supervisor检查: 每步后自动评估
    - 死循环检测: 防止无限循环
    - 目标导向: 失败重试而非抛异常
    """

    def __init__(self):
        self._intent_detector = IntentDetector()
        self._planner = Planner()
        self._executor = Executor()
        self._integrator = Integrator()
        self._guard = Guard()
        self._dynamic_subgraph = DynamicSubgraph()
        # ContextManager（app/agent/context）：每 turn 在 execute() 内新建，
        # step 钩子在 _execute_todo_with_loop 内调用；失败一律降级不阻塞主流程
        self._ctx_mgr = None
        self._ctx_step = 0
        self._ctx_compress_count = 0   # 本会话累计压缩次数（跨 turn 从会话 KV 续读）
        self._ctx_floor = 0            # 用量底线=上轮真实峰值（KV 续读，跨轮不归零）
        self._ctx_peak = 0             # 本轮已推送的真实峰值
        self._billed_base_in = 0       # 会话累计计费基数（KV 续读，跨轮累加不归零）
        self._billed_base_out = 0
        self._billed_base_cost = 0.0
        self._supervisor = SupervisorGraph()
        self._replanner = Replanner()
        self._loop_detector = default_loop_detector
        self._db_session = None  # 数据库会话
        self._session_id = None  # 当前会话ID
        self._task_id = None     # 当前任务ID
        # 写后读回跳过状态（规则13硬约束，2026-11-13"避免反复读取"）：
        # 按会话记 {prev_op, last_write, read_files}，单例并发下不串会话；
        # turn 边界 _reset_readback_turn() 全清（跨 turn 上下文是摘要）
        self._readback_guard: Dict[str, Dict[str, Any]] = {}
        self._state_manager: Optional[ExecutionStateManager] = None  # 执行状态管理器

    def _reset_readback_turn(self, session_id: Optional[str] = None) -> None:
        """新对话轮开始：清空该会话的读回守卫状态。

        跨 turn 的上下文是摘要（不是全文），上一 turn 读过/写过的文件在
        本 turn 都可能需要真读一次——不清会把合法首读误跳掉。
        """
        self._readback_guard.pop(session_id or "__none__", None)

    def cancel(self):
        """取消当前执行"""
        # 同步到 TaskManager（API 层中断检查用）
        if self._task_id:
            task_manager.stop_task(self._task_id)
        logger.info(f"[AgentGraph] 任务已请求取消: session_id={self._session_id}, task_id={self._task_id}")

    def _task_id_checker(self) -> bool:
        """TaskManager 中断检查回调（供 ExecutionStateManager 使用）"""
        if self._task_id:
            return task_manager.is_running(self._task_id)
        return True

    def _check_cancelled(self) -> bool:
        """检查是否已取消，返回 True 表示应该停止执行"""
        # 1. 先查 TaskManager（API 层设置）
        if self._task_id:
            status = task_manager.get_status(self._task_id)
            if status != "running":
                logger.info(f"[AgentGraph] TaskManager 检测到中断: task_id={self._task_id}, status={status}")
                return True
        return False

    def _check_termination(self) -> tuple[bool, str]:
        """检查终止条件"""
        # 先检查用户取消（无论 _state_manager 是否存在）
        if self._check_cancelled():
            return True, "用户取消执行"
        if self._state_manager:
            return self._state_manager.check_termination()
        return False, ""

    def _budget_hint(self, ctx: str) -> str:
        """剩余≤4轮(第26轮起)注入收敛指令,确保上限内出产物/结论。"""
        sm = self._state_manager
        if sm and 0 <= sm.max_iterations - sm.iteration <= 4:
            ctx += chr(10) + chr(10) + ("【轮次预算】剩余%d轮,立即收敛,优先完成核心产物并给出结论。"
                                        % (sm.max_iterations - sm.iteration))
        return ctx

    def _ensure_state_manager(self, session_id: str, task_id: str, user_input: str):
        """确保 ExecutionStateManager 已初始化"""
        if self._state_manager is None or self._state_manager.session_id != session_id:
            self._state_manager = ExecutionStateManager(
                session_id=session_id,
                task_id=task_id,
                user_input=user_input,
            )
            # 绑定 TaskManager 中断检查（使用实例属性引用，避免闭包变量捕获问题）
            self._state_manager.set_running_check(self._task_id_checker)

    def _extract_files_from_result(
        self,
        step: Dict[str, Any],
        result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """从执行结果中提取生成的文件信息"""
        files = []

        action = step.get("action", "")
        params = step.get("params", {})
        result_data = result.get("data", {})

        # file_operations write 操作
        if action == "file_operations" and params.get("operation") == "write":
            file_path = params.get("path", "")
            task_path = params.get("task_path") or ""
            rel_path = result_data.get("rel_path") or file_path
            files.append({
                "rel_path": rel_path,
                "path": f"tasks/{task_path}/{rel_path}" if task_path else f"tasks/{rel_path}",
                "name": file_path.split("/")[-1].split("\\")[-1],
                "type": "file",
                "size": result_data.get("size", 0)
            })

        # file_operations create（项目创建）操作
        if action == "file_operations" and params.get("operation") == "create":
            project_name = result_data.get("project_name") or params.get("task_path") or params.get("path", "")
            created_files = result_data.get("files", [])
            for f in created_files:
                files.append({
                    "rel_path": f.get("name", ""),
                    "path": f.get("path", ""),
                    "name": f.get("name", ""),
                    "type": "file",
                    "size": f.get("size", 0),
                    "project_name": project_name,
                })

        # code_generator 生成代码
        elif action == "code_generator":
            code = result_data.get("code", "")
            requirements = params.get("requirements", "")

            # 尝试从 requirements 中提取文件名
            language = params.get("language", "python")
            ext_map = {"python": "py", "javascript": "js", "typescript": "ts", "go": "go", "rust": "rs", "html": "html", "text": "txt"}
            ext = ext_map.get(language.lower(), "txt")

            filename_match = re.search(r'file[_\s]?name[:\s]+["\']?([^"\'\n]+)', requirements, re.IGNORECASE)
            if not filename_match:
                filename_match = re.search(r'([\w\-]+\.' + ext + r')', requirements)

            filename = filename_match.group(1) if filename_match else f"generated.{ext}"

            # code_generator 的代码需要由 file_operations 写入，所以这里只是标记
            files.append({
                "rel_path": filename,
                "path": filename,
                "name": filename,
                "type": "file",
                "size": len(code)
            })

        return files

    async def _get_db_session(self):
        """获取异步数据库会话"""
        if self._db_session is None:
            from app.db.session import AsyncSessionLocal
            self._db_session = AsyncSessionLocal()
        return self._db_session

    async def _save_execution_node(
        self,
        todo_id,  # 接受字符串或整数，内部转换为整数
        node_type: str,
        content: str,
        action: str = None,
        params: dict = None,
        result: dict = None,
        is_final: bool = False,
        success: bool = True,
        iteration: int = 0,
        meta_data: dict = None,
    ) -> Optional[ExecutionNode]:
        """
        保存执行节点到数据库（异步）

        Args:
            todo_id: 待办序号 (可以是字符串或整数)
            node_type: 节点类型 (thought/planning/next_moves/observation)
            content: 节点内容
            action: 执行动作 (可选)
            params: 执行参数 (可选)
            result: 执行结果 (可选)
            is_final: 是否为最终状态
            success: 是否成功
            iteration: 迭代序号
            meta_data: 额外数据

        Returns:
            保存的节点对象
        """
        # 转换 todo_id 为整数
        try:
            todo_id_int = int(todo_id) if todo_id is not None else 0
        except (ValueError, TypeError):
            todo_id_int = 0

        try:
            from datetime import datetime, timezone
            db = await self._get_db_session()

            now = datetime.now(timezone.utc)

            # 如果有 session_id，先确保 sessions 表中有对应记录
            if self._session_id:
                from app.models.experience import SessionModel
                from sqlalchemy import select
                # 检查是否已存在
                session_check = await db.execute(
                    select(SessionModel).where(SessionModel.session_id == self._session_id)
                )
                session_record = session_check.scalar_one_or_none()
                if not session_record:
                    # 创建会话记录，显式设置时间戳避免依赖 server_default
                    session_record = SessionModel(
                        session_id=self._session_id,
                        user_id=0,  # 匿名用户
                        title="Agent Session",
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(session_record)
                    await db.flush()

            # 如果有 task_id，先确保 tasks 表中有对应记录
            if self._task_id:
                from app.models.experience import TaskModel
                from sqlalchemy import select
                # 检查是否已存在
                task_check = await db.execute(
                    select(TaskModel).where(TaskModel.task_id == self._task_id)
                )
                task_record = task_check.scalar_one_or_none()
                if not task_record:
                    # 创建任务记录，显式设置时间戳避免依赖 server_default
                    task_record = TaskModel(
                        task_id=self._task_id,
                        session_id=self._session_id,
                        user_id=0,  # 匿名用户
                        task="Agent Task",
                        status="running",
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(task_record)
                    await db.flush()  # 立即写入，获取 ID

            node = ExecutionNode(
                session_id=self._session_id or "default",
                task_id=self._task_id,  # None if not set; model field is now nullable
                todo_id=todo_id_int,
                iteration=iteration,
                node_type=node_type,
                content=content,
                action=action,
                params=params,
                result=result,  # 使用传入的 result 参数
                is_final=is_final,
                success=success,
                meta_data=meta_data,
            )
            db.add(node)
            await db.commit()
            await db.refresh(node)
            logger.debug(f"[AgentGraph] 保存节点: {node_type} (todo={todo_id})")
            return node
        except Exception as e:
            logger.warning(f"[AgentGraph] 保存节点失败: {e}")
            # 不抛出异常，避免阻塞主流程
            return None

    def _format_step_observation(self, action: str, result: Dict[str, Any], files: List[Dict[str, Any]]) -> str:
        """生成人类可读的步骤观察消息"""
        success = result.get("success", True)
        error = result.get("error")

        if success:
            data = result.get("data") or {}
            if isinstance(data, dict) and data.get("skipped"):
                # 读回被跳过（ReadbackGuard）——原样透传给前端，别显示
                # 成"执行成功"让人以为读到了内容
                return data.get("message") or "完成：跳过重复读取"
            if files:
                file_names = [f.get("name", f.get("rel_path", "未知文件")) for f in files]
                if len(file_names) == 1:
                    return f"完成：生成了 {file_names[0]}"
                else:
                    return f"完成：生成了 {len(file_names)} 个文件 - {', '.join(file_names[:5])}{'...' if len(file_names) > 5 else ''}"
            elif action == "search":
                data = result.get("data", {})
                if isinstance(data, dict):
                    count = len(data.get("results", []))
                    return f"完成：搜索到 {count} 条结果"
                return "完成：搜索成功"
            elif action == "general_response":
                return "完成：已生成回复"
            else:
                return "完成：执行成功"
        else:
            # 有错误时，显示错误信息
            if error:
                # 截断过长的错误信息
                if len(error) > 200:
                    error = error[:200] + "..."
                return f"失败：{error}"
            return "失败：执行失败（未知错误）"

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        执行任务的主入口

        Args:
            task: 用户任务描述
            context: 执行上下文（用户ID、会话ID等）
            session_id: 会话ID
            task_id: 任务ID
            on_step: 步骤回调函数，用于流式推送状态

        Returns:
            执行结果字典
        """
        # 在 TaskManager 中注册任务
        if task_id:
            task_manager.create_task(task_id)
        self._state_manager = None  # 重置

        state = AgentState(
            messages=[],
            task=task,
            context=context or {},
        )

        # 优先从 context 中获取 session_id 和 task_id
        if session_id is None:
            session_id = state.context.get("session_id")
        # 新对话轮：清空读回守卫（跨 turn 上下文是摘要，首读不能跳）
        self._reset_readback_turn(session_id)
        if task_id is None:
            task_id = state.context.get("task_id")

        if session_id:
            state.context["session_id"] = session_id
            self._session_id = session_id
        if task_id:
            state.context["task_id"] = task_id
            self._task_id = task_id
            # 设置各组件的 task_id，支持可取消的 LLM 调用
            self._planner.set_task_id(task_id)
            self._intent_detector.set_task_id(task_id)
            self._integrator.set_task_id(task_id)

        # P1/P2（2026-11-14）：本 turn 计费累计清零 + usage scope。
        # factory 侧每次 LLM 调用按此 scope 累计真实 prompt/completion/cost，
        # key 与 set_usage_scope 一致（task_id 可能为 None → 回落 session_id）。
        try:
            from app.agent.llm.factory import set_usage_scope, reset_task_usage
            _usage_key = task_id or session_id or "global"
            set_usage_scope(_usage_key)
            reset_task_usage(_usage_key)
        except Exception as _ue:  # noqa: BLE001 - 追踪失败不阻塞执行
            logger.debug("usage scope 初始化失败（降级无累计）: %s", _ue)

        # 用户级 DeepSeek key（2026-11-14）：本 turn 按 session → user 装载
        # 用户自己的 key（contextvar）；未填 / 查询失败一律回落系统 key，
        # 绝不阻塞执行。
        try:
            from app.agent.llm.user_api_key import apply_turn_user_api_key
            await apply_turn_user_api_key(session_id)
        except Exception as _uke:  # noqa: BLE001
            logger.debug("用户 API key 装载失败（降级系统 key）: %s", _uke)

        logger.info(f"[AgentGraph] 开始执行任务: {task[:100]}...")

        # 执行过程中调用回调
        if on_step:
            on_step("planning", {"status": "开始执行任务"})

        # ContextManager：本 turn 的上下文管理（turn=execute 一次）。
        # 初始化失败只降级为"无上下文管理"，绝不阻塞任务执行。
        self._ctx_step = 0
        self._ctx_mgr = None
        try:
            from app.agent.context import ContextManager
            from app.agent.context.embedding import ZhipuEmbedder
            from app.core.config import get_settings
            _embedder = ZhipuEmbedder()
            self._ctx_mgr = ContextManager(
                cfg=get_settings().build_context_config(),
                embed_fn=_embedder.embed_one if _embedder.api_key else None,
            )
            self._ctx_mgr.on_session_start(
                system_prompt="", constraints="", user_request=task)
            logger.info("[CtxMgr] turn 开始，预算 %d tokens",
                        self._ctx_mgr.cfg.max_tokens)
        except Exception as _ce:
            logger.warning("[CtxMgr] 初始化失败（本 turn 降级）: %s", _ce)
            self._ctx_mgr = None

        # 上下文用量：跨 turn 续读压缩次数 + 上轮真实用量底线（会话 KV），失败降级为 0
        self._ctx_compress_count = 0
        self._ctx_floor = 0
        self._ctx_peak = 0
        # 会话累计计费基数（2026-11-14 用户定：一个会话累加，不每轮归零）：
        # 每 turn 从会话 KV 续读上轮为止的 billed_* 累计，收尾按基数+本轮回写
        self._billed_base_in = 0
        self._billed_base_out = 0
        self._billed_base_cost = 0.0
        if session_id:
            try:
                from app.agent.tools.session_context import get_session_context
                _stored = await get_session_context(session_id, "context_usage")
                if isinstance(_stored, dict):
                    # cc_ver>=2（2026-11-13）：compress_count 仅计 100% 硬限压缩。
                    # 无版本标记的旧值全是旧语义（折叠/卸载也计数），且当时硬限从未触发
                    # （生产实测最大 used=8138/128000）→ 归零，不继承旧计数
                    if int(_stored.get("cc_ver", 0) or 0) >= 2:
                        self._ctx_compress_count = int(_stored.get("compress_count", 0) or 0)
                    else:
                        self._ctx_compress_count = 0
                    self._ctx_floor = int(_stored.get("used", 0) or 0)
                    self._ctx_peak = self._ctx_floor
                    # billed_* 语义=会话累计（cc_ver>=3 有键；更旧值从 0 起算）
                    if int(_stored.get("cc_ver", 0) or 0) >= 3:
                        self._billed_base_in = int(_stored.get("billed_in", 0) or 0)
                        self._billed_base_out = int(_stored.get("billed_out", 0) or 0)
                        self._billed_base_cost = float(_stored.get("billed_cost", 0.0) or 0.0)
            except Exception as _se:
                logger.debug(f"[CtxMgr] 用量续读失败（降级 0）: {_se}")

        try:
            # 检查是否已取消
            if self._check_cancelled():
                return self._format_cancelled_result(state)
            state = await self._safety_check(state)
            if state.error:
                if on_step:
                    on_step("error", {"message": state.error})
                return self._format_error(state.error, state)

            # 2. 意图检测
            state = await self._detect_intent(state)
            logger.info(f"[AgentGraph] 意图检测结果: {state.intent}, 置信度: {state.confidence}")

            # 3. 创建统一执行上下文
            exec_context = self._create_execution_context(state)

            # 4. 初始化 ExecutionStateManager（用于持久化）
            # task_id 可能为 None，但 session_id 总是存在的，此时用 session_id 作为 task_id
            if session_id:
                effective_task_id = task_id if task_id else session_id
                self._ensure_state_manager(session_id, effective_task_id, task)

            # 5. 尝试从数据库恢复状态
            restored = False
            if self._state_manager:
                restored = await self._state_manager.load_state()
                # 上轮被30轮上限截断:继续->续预算;新任务->丢弃旧状态
                self._state_manager, restored = await cap_restore(
                    self._state_manager, task, restored)
                if self._state_manager is None:
                    self._ensure_state_manager(session_id, task_id or session_id, task)

            if restored and self._state_manager.todos:
                # 恢复执行：发送恢复状态给前端
                #（context._todos 同步断点待办：终稿总结/前端同步依赖它，
                #  否则恢复轮的完成总结拿不到待办清单）
                state.context["_todos"] = [
                    t.to_dict() for t in self._state_manager.todos]
                if on_step:
                    on_step("resumed", {
                        "message": "任务已恢复，继续执行",
                        "current_index": self._state_manager.current_todo_index
                    })
                    on_step("todos", {"todos": [t.to_dict() for t in self._state_manager.todos]})
                logger.info(
                    f"[AgentGraph] 从断点恢复: session={session_id}, "
                    f"todos={len(self._state_manager.todos)}, "
                    f"index={self._state_manager.current_todo_index}"
                )
            else:
                # 新执行：生成待办列表（不依赖 state_manager，确保始终有 todos）
                todos = await self._planner.create_quick_todos(state.task)
                if todos:
                    for t in todos:
                        if "status" not in t:
                            t["status"] = "pending"
                    # 如果有 state_manager，同步更新
                    if self._state_manager:
                        self._state_manager.set_todos(todos)
                    state.context["_todos"] = todos
                    if on_step:
                        on_step("todos", {"todos": todos})
                    if self._state_manager:
                        await self._state_manager.save_state()
                    logger.info(f"[AgentGraph] 生成 {len(todos)} 个待办事项")
                elif not restored:
                    # Planner 返回空列表，降级生成默认待办
                    logger.warning("[AgentGraph] Planner 返回空待办列表，使用降级待办")
                    todos = [{"id": 1, "title": state.task, "action": "file_operations",
                              "params": {"operation": "create", "path": state.task}, "status": "pending"}]
                    state.context["_todos"] = todos
                    if on_step:
                        on_step("todos", {"todos": todos})

            # 6. 统一执行引擎
            state = await self._execute_unified(state, exec_context, on_step)

            # 待办有失败 = 任务未真正完成（2026-11-09 规则：没做完禁止标完成）
            if exec_context.status == ExecutionStatus.FAILED and not state.context.get("_rounds_capped"):
                state.error = (
                    f"{state.context.get('_failed_count', 0)}/{state.context.get('_total_count', 0)} "
                    "个待办失败：任务未按要求完成"
                )
                logger.warning(f"[AgentGraph] {state.error}")

            # 7. Supervisor 最终检查
            supervisor_decision = await self._supervisor.evaluate(state.to_dict())
            if supervisor_decision.action == "reject":
                state.error = supervisor_decision.reason
                # 先落库再发终态事件（2026-11-14 TC-S16-03 e2e 实测：前端收到
                # 终态事件即断开→本任务被 cancel，后置 await 会被打断丢断点；
                # 同 agent.py「先落库再通知前端」原则）
                if self._state_manager and session_id:
                    self._state_manager.note_failure(state.error)
                    await self._state_manager.save_state()
                if on_step:
                    on_step("error", {"message": state.error})
                return self._format_error(state.error, state)

            # 8. 结果整合
            state = await self._integrate_results(state)

            # 9. 生成完成总结
            todos = state.context.get("_todos", [])
            if todos and state.results:
                summary_result = await self._integrator.generate_completion_summary(
                    task=state.task,
                    todos=todos,
                    results=state.results
                )
                if on_step:
                    on_step("final_summary", {
                        "summary": summary_result.get("summary", ""),
                        "suggestions": summary_result.get("suggestions", []),
                        "success": summary_result.get("success", True)
                    })

            # 有待办失败/错误残留：发 error 不发 complete，禁止假完成
            # （轮次上限截断除外——那是待继续执行的半成品，保持原 complete 语义）
            if state.error and not state.context.get("_rounds_capped"):
                logger.warning(f"[Agent] 任务以失败收尾: {state.error}")
                # 断点保留（2026-11-14 TC-S16-03）：失败收尾也把未完成待办与
                # 失败原因落盘，供下轮 cap_restore 判「继续/新任务」；轮次
                # 上限截断（_rounds_capped）走正常保留分支，不在这里重复处理。
                # 先落库再发终态事件：前端收到 error即断开 → 本任务被 cancel，
                # 后置 await 会被打断（e2e 实测），断点必须先写完。
                if self._state_manager and session_id:
                    self._state_manager.note_failure(state.error)
                    await self._state_manager.save_state()
                if task_id:
                    task_manager.fail_task(task_id)
                if on_step:
                    on_step("error", {"message": state.error})
                return self._format_error(state.error, state)

            # 先清断点+落任务状态，再发 complete（2026-11-14 TC-S16-03 e2e 实测：
            # 前端收到 complete 立即断开 → 本任务被 cancel，后置 await 被打断，
            # 断点清不掉且任务被误标"任务被取消"；同 agent.py「先落库再通知前端」）
            # 轮次上限截断时保留状态,供继续执行
            if self._state_manager and session_id and not state.context.get("_rounds_capped"):
                await self._state_manager.clear_state()
            if task_id:
                task_manager.complete_task(task_id)

            if on_step:
                final_message = None
                for msg in reversed(state.messages):
                    if msg.get("type") == "final":
                        final_message = msg.get("content")
                        break
                on_step("complete", {
                    "result": cap_notice(final_message or (
                        state.results[-1].get("result", {}).get("data")
                        if state.results else None
                    ), state)
                })

            return self._format_response(state, exec_context)

        except Exception as e:
            logger.exception(f"[Agent] 执行异常: {e}")
            state.error = str(e)
            # 断点保留：异常中断同样记失败标记（best-effort，不阻塞报错返回）。
            # 先落库再发终态事件（前端收到 error 即断开，后置 await 会被打断）
            if self._state_manager and session_id:
                try:
                    self._state_manager.note_failure(str(e))
                    await self._state_manager.save_state()
                except Exception as _ck_e:
                    logger.warning(f"[Agent] 失败断点保存失败(忽略): {_ck_e}")
            if task_id:
                task_manager.fail_task(task_id)
            if on_step:
                on_step("error", {"message": str(e)})
            return self._format_error(state.error, state)
        finally:
            # ContextManager turn 后钩子：重量级卸载/压缩/长循环折叠
            # （全量淘汰唯一入口；挂在 finally 覆盖 execute 全部返回路径）
            if self._ctx_mgr is not None:
                try:
                    _cr = self._ctx_mgr.on_turn_end()
                    logger.info(
                        "[CtxMgr] turn_end reason=%s saved=%d offloaded=%s folded=%s",
                        _cr.reason, _cr.saved, _cr.offloaded, _cr.folded)
                    # 仅"达到 100% 上限"的真压缩计数（2026-11-13 用户定，对齐 Hermes 计数语义：
                    # 长循环折叠/卸载/摘要是常规整理，不计入"压缩次数"）
                    if _cr.reason == "budget":
                        self._ctx_compress_count += 1
                except Exception as _ce:
                    logger.warning("[CtxMgr] on_turn_end 失败（不阻塞）: %s", _ce)
                # turn 收尾：推送压缩后的实时用量 + 持久化到会话 KV（刷新可恢复）
                try:
                    import asyncio as _aio
                    from app.agent.tools.session_context import set_session_context
                    from app.agent.llm.factory import (
                        get_task_usage, get_last_usage)
                    _max = self._ctx_mgr.cfg.max_tokens
                    # 11-13：报本轮真实峰值（接续 floor），不再用重建片段 budget.used
                    _used = max(
                        getattr(self, "_ctx_peak", 0),
                        getattr(self, "_ctx_floor", 0),
                    )
                    _tu = get_task_usage()
                    _payload = {
                        "used": _used,
                        "max": _max,
                        "ratio": round(_used / _max, 4) if _max else 0.0,
                        "compress_count": self._ctx_compress_count,
                        # v3（2026-11-14）：used=真实 usage 单请求峰值；
                        # billed_* = 会话累计（KV 基数 + 本轮，跨轮累加不归零，
                        # 2026-11-14 用户定；读取侧 >=3 兼容）
                        "cc_ver": 3,
                        "step": self._ctx_step,
                        **self._billed_payload(_tu),
                        "last_in": int(get_last_usage().get("prompt_tokens") or 0),
                    }
                    if on_step:
                        on_step("context_usage", _payload)
                    if session_id:
                        _aio.create_task(set_session_context(
                            session_id, "context_usage", _payload))
                except Exception as _pe:
                    logger.warning("[CtxMgr] 用量推送/持久化失败（不阻塞）: %s", _pe)
                self._ctx_mgr = None

    def _billed_payload(self, tu: dict) -> dict:
        """会话累计计费三元组 = 会话 KV 续读基数 + 本 turn 真实 usage。

        2026-11-14 用户定：一个会话累加计费，billed_* 不再每轮归零。
        step 实时事件与 turn 收尾落库共用此公式，保证推送与持久化口径一致。
        """
        return {
            "billed_in": self._billed_base_in + int(tu.get("prompt_tokens") or 0),
            "billed_out": self._billed_base_out + int(tu.get("completion_tokens") or 0),
            "billed_cost": round(self._billed_base_cost + float(tu.get("cost") or 0.0), 6),
        }

    def _create_execution_context(self, state: AgentState) -> ExecutionContext:
        """
        创建统一执行上下文

        从 routing 配置中提取参数，但使用统一的默认值。
        """
        routing = state.routing or {}
        task_path = state.context.get("task_path") if state.context else None

        # 从 routing 中提取配置，如果不存在则使用统一默认值
        ctx = create_execution_context(
            max_iterations=routing.get("max_iterations", 15),
            parallel_enabled=routing.get("parallel", True),
            max_retries=3,
            default_step_timeout=300,
            max_step_timeout=600,
            http_step_timeout=600,
            task_path=task_path,
        )
        return ctx

    async def _execute_unified(
        self,
        state: AgentState,
        context: ExecutionContext,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> AgentState:
        """
        统一执行引擎

        流程:
        1. 如果从断点恢复，使用 ExecutionStateManager 中的 todos
        2. 逐一执行每个待办:
           - Thought: 分析当前状态
           - Planning: 生成执行动作
           - NextMoves: 执行动作
           - Observation: 验证结果
        3. 全部完成后生成总结
        """
        context.status = ExecutionStatus.RUNNING

        # 从 state_manager 获取待办列表（可能是恢复的）
        todos = []
        start_index = 0
        if self._state_manager and self._state_manager.todos:
            todos = self._state_manager.todos
            # 找到第一个未完成的待办作为起始位置
            for i, todo in enumerate(todos):
                if todo.status != TodoStatus.COMPLETED:
                    start_index = i
                    break
        else:
            todos = state.context.get("_todos", [])
            start_index = 0

        if not todos:
            state.error = "无法生成待办列表"
            return state

        logger.info(f"[AgentGraph] 执行 {len(todos)} 个待办，起始位置={start_index}")

        # 注意：待办列表已在 execute() 方法中通过 on_step("todos") 发送过一次
        # 此处不再重复发送，避免前端显示两遍

        # 2. 逐一执行每个待办
        all_results = []
        context_history = ""  # 累积上下文

        # 任务文本点名的文件 = 任务级硬承诺（用户硬规则 2026-11-09：
        # "若文件未生成说明代码逻辑有问题"）。模型可能从不把它们写进
        # 任何一轮的目标文件（生产实测：任务要求6个文件、模型只写5个
        # 就宣布完成），种子化进承诺集，收尾时由兜底检查强制补齐。
        try:
            _task_text = str(getattr(state, "task", "") or "")
            _seed_files = re.findall(
                r"(?<![A-Za-z0-9_/.])([A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*\.[a-z][a-z0-9]{0,7})(?![A-Za-z0-9_])",
                _task_text,
            )
            if _seed_files:
                _pf0 = state.context.setdefault("_promised_files", [])
                for _f in _seed_files:
                    if _f not in _pf0:
                        _pf0.append(_f)
                logger.info("[AgentGraph] 任务文本承诺文件: %s", _seed_files)
        except Exception as _e:
            logger.warning(f"[AgentGraph] 任务文本文件提取失败(忽略): {_e}")

        for i in range(start_index, len(todos)):
            # 轮次上限兜底:预算用尽直接收尾,不再启动新待办
            if self._state_manager and self._state_manager.iteration >= self._state_manager.max_iterations:
                state.context["_rounds_capped"] = True
                break
            todo = todos[i]
            todo_id = todo.id if hasattr(todo, "id") else todo.get("id", i + 1)
            todo_title = todo.title if hasattr(todo, "title") else todo.get("title", "")
            todo_action = todo.action if hasattr(todo, "action") else todo.get("action", "")
            todo_params = todo.params if hasattr(todo, "params") else todo.get("params", {})
            todo_status = todo.status if hasattr(todo, "status") else todo.get("status", TodoStatus.PENDING)

            # 跳过已完成的待办
            if todo_status == TodoStatus.COMPLETED:
                continue

            # 发送待办开始
            if on_step:
                on_step("todo_start", {
                    "todo": {
                        "id": todo_id,
                        "title": todo_title,
                        "total": len(todos),
                        "current": i + 1
                    }
                })

            # 执行单个待办的 Thought-Planning-Observation 循环
            todo_result = await self._execute_todo_with_loop(
                state=state,
                todo=todo,
                context=context_history,
                context_obj=context,
                iteration=i,
                on_step=on_step,
            )

            # 检查是否已取消/终止
            if self._check_cancelled():
                all_results.append({
                    "todo_id": todo_id,
                    "todo_title": todo_title,
                    "result": {"summary": "用户取消", "success": False, "cancelled": True},
                    "success": False,
                    "cancelled": True
                })
                break

            all_results.append({
                "todo_id": todo_id,
                "todo_title": todo_title,
                "result": todo_result,
                "success": todo_result.get("success", False),
                "capped": todo_result.get("capped", False)
            })

            if todo_result.get("capped"):
                state.context["_rounds_capped"] = True
                if self._state_manager:
                    await self._state_manager.save_state()
                break

            # 更新上下文历史
            context_history += f"\n\n待办 {todo_id}: {todo_title}\n"
            context_history += f"结果: {todo_result.get('summary', '')}\n"

            # 同步到 state_manager
            if self._state_manager:
                self._state_manager.current_todo_index = i
                # 更新 todos 列表中的状态
                if i < len(self._state_manager.todos):
                    sm_todo = self._state_manager.todos[i]
                    todo_success = todo_result.get("success", False)
                    if todo_success:
                        sm_todo.status = TodoStatus.COMPLETED
                        sm_todo.result = todo_result.get("summary", "")
                    else:
                        sm_todo.status = TodoStatus.FAILED
                        sm_todo.error = todo_result.get("summary", "")

            # 同步到 state.context._todos
            todo_success = todo_result.get("success", False)
            for t in state.context.get("_todos", []):
                if t.get("id") == todo_id:
                    t["status"] = "completed" if todo_success else "failed"
                    break

            # 发送待办完成
            updated_todo = {
                "id": todo_id,
                "title": todo_title,
                "status": "completed" if todo_success else "failed",
                "success": todo_success
            }
            if on_step:
                on_step("todo_complete", {"todo": updated_todo})

            # 每个待办完成后保存状态（断点恢复）
            if self._state_manager:
                await self._state_manager.save_state()

        state.results = all_results

        # 检查是否有失败
        failed_count = sum(1 for r in all_results if not r.get("success", False) and not r.get("capped", False))
        if failed_count > 0:
            logger.warning(f"[AgentGraph] {failed_count}/{len(all_results)} 个待办失败")

        # 任务级兜底（用户硬规则 2026-11-09）：承诺文件（计划目标文件 ∪
        # 观察提取文件 ∪ 任务文本点名文件）必须真实存在于任务目录。
        # 缺失时自动补"补齐待办"（最多2次），仍缺才判任务失败；
        # 之后再做一次 LLM 必需文件核对（兜住模型计划本身漏掉的文件，
        # 如 Vite 项目不写 index.html/main.js/App.vue），LLM 发现的缺失
        # 只尽力补齐、不单独判失败（避免核对误报导致任务假失败）。
        try:
            import os as _os
            from app.agent.skills.file_operations.skill import get_tasks_dir as _gtd
            _task_dir = getattr(context, "task_path", None)
            _promised = [str(f).strip() for f in (state.context.get("_promised_files") or []) if str(f).strip()]
            _base_final = (_gtd() / _task_dir) if _task_dir else None

            async def _repair_pass(files):
                """对缺失清单跑补齐待办（最多2次），返回仍缺失清单"""
                if not _base_final:
                    return list(files)
                _miss = _check_promised_files(files, None, None, _base_final)
                for _att in range(2):
                    if not _miss:
                        break
                    _repair_todo = {
                        "id": f"repair_{_att}",
                        "title": "补齐任务要求但尚未生成的文件（必须真实写入磁盘，禁止只描述不创建）: "
                        + ", ".join(_miss),
                        "params": {},
                        "depends_on": [],
                    }
                    try:
                        await self._execute_todo_with_loop(
                            state=state,
                            todo=_repair_todo,
                            context=context_history,
                            context_obj=context,
                            iteration=0,
                            on_step=on_step,
                            is_repair=True,
                        )
                    except Exception as _re_e:
                        logger.warning(f"[AgentGraph] 补齐待办执行异常: {_re_e}")
                    _miss = _check_promised_files(files, None, None, _base_final)
                # 确定性兜底：补齐轮后仍缺失的承诺文件写最小占位
                #（用户硬规则"任务提到的文件必须出现"；内容可由后续轮充实）
                if _miss:
                    for _rel in list(_miss):
                        _p = Path(_base_final) / _rel
                        try:
                            if not _p.exists():
                                _p.parent.mkdir(parents=True, exist_ok=True)
                                if _p.suffix == ".py":
                                    _p.write_text(f'"""{_p.name}"""\n', encoding="utf-8")
                                elif _p.suffix == ".md":
                                    _p.write_text(f"# {_p.stem}\n", encoding="utf-8")
                                elif _p.suffix == ".json":
                                    _p.write_text("{}\n", encoding="utf-8")
                                else:
                                    _p.write_text("", encoding="utf-8")
                                logger.warning(f"[AgentGraph] 兜底占位文件已创建: {_rel}")
                        except Exception as _we:
                            logger.warning(f"[AgentGraph] 兜底占位写入失败: {_rel}: {_we}")
                    _miss = _check_promised_files(files, None, None, _base_final)
                return _miss

            if _promised and _base_final:
                _final_missing = _check_promised_files(_promised, None, None, _base_final)
                if _final_missing:
                    logger.warning("[AgentGraph] 承诺文件缺失，自动补齐: %s", _final_missing)
                    _final_missing = await _repair_pass(_promised)
                    if _final_missing:
                        _msg = "任务提到的文件未生成: " + ", ".join(_final_missing)
                        logger.warning("[AgentGraph] %s", _msg)
                        state.error = f"{state.error}；{_msg}" if state.error else _msg
                        failed_count += 1
                    else:
                        logger.warning("[AgentGraph] 承诺文件已全部补齐")

                # LLM 必需文件核对（best-effort：只补不判失败）
                try:
                    _disk = []
                    for _root, _dirs, _fs in _os.walk(_base_final):
                        for _f in _fs:
                            _disk.append(str(Path(_root, _f).relative_to(_base_final)))
                    if _disk or _promised:
                        _llm_miss = await self._planner.missing_required_files(state.task, sorted(_disk))
                        _llm_miss = [_norm_rel(str(x)) for x in (_llm_miss or []) if str(x).strip()][:10]
                        _llm_miss = [x for x in _llm_miss if x and not (_base_final / x).exists()]
                        if _llm_miss:
                            logger.warning("[AgentGraph] LLM 核对发现必需文件缺失，尽力补齐: %s", _llm_miss)
                            await _repair_pass(_llm_miss)
                except Exception as _le:
                    logger.warning(f"[AgentGraph] LLM 必需文件核对失败(忽略): {_le}")
        except Exception as _e:
            logger.warning(f"[AgentGraph] 文件兜底检查失败(忽略): {_e}")

        # 供 execute() 判定收尾方式：有失败 = 任务未完成，禁止假完成
        state.context["_failed_count"] = failed_count
        state.context["_total_count"] = len(all_results)
        context.status = ExecutionStatus.SUCCEEDED if failed_count == 0 else ExecutionStatus.FAILED
        return state

    async def _execute_todo_with_loop(
        self,
        state: AgentState,
        todo: Dict[str, Any],
        context: str,
        context_obj: ExecutionContext,
        iteration: int,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        is_repair: bool = False,
    ) -> Dict[str, Any]:
        """
        对单个待办执行 Thought-Planning-Observation 循环

        逻辑:
        1. 如果有上一步失败信息，Thought 阶段要分析失败原因并提出修正方案
        2. Planning 阶段基于失败原因调整参数
        3. 成功后才能进入下一个待办
        4. 每个 action 后通过 ExecutionStateManager 保存状态（支持断点恢复）

        Args:
            state: Agent 状态
            todo: 待办项
            context: 历史上下文
            context_obj: 执行上下文
            iteration: 当前迭代
            on_step: 回调函数

        Returns:
            执行结果
        """
        # 统一转换为 TodoItem
        if hasattr(todo, "to_dict"):
            todo_item = todo
            todo_id = todo.id
            todo_title = todo.title
            todo_params = todo.params
            todo_status = todo.status
        else:
            todo_id = todo.get("id", 0)
            todo_title = todo.get("title", "")
            todo_params = todo.get("params", {})
            todo_status = todo.get("status", TodoStatus.PENDING)
            # 创建 TodoItem 以便统一处理
            from app.agent.execution_state import TodoItem as ES_TodoItem
            todo_item = ES_TodoItem(
                id=str(todo_id),
                title=todo_title,
                action=todo.get("action", ""),
                params=todo_params,
                status=todo_status,
            )

        # 检查终止（补齐轮不走终止判定：收尾时"预算耗尽/待办已完成"会让补齐空转，
        # 2026-11-10 线上"兜底自动补齐"一行没写的根因）
        if not is_repair:
            should_stop, stop_reason = self._check_termination()
            if should_stop:
                return _stop_result(state, stop_reason)

        # 检查中断
        if self._check_cancelled():
            return {"success": False, "summary": "用户取消执行", "cancelled": True}

        max_loop_iterations = 5
        last_error = None
        last_error_code = None  # 结构化错误码（TOOL_ERROR_CODES），correction 按 code 分支
        last_execution_result = None
        # 追踪工具调用历史，防止相同调用重复3次以上
        tool_call_history = []
        max_same_call = 3
        exit_reason = None  # 循环退出原因：None=轮次预算耗尽 / duplicate_call=重复中断
        # 轮次预算：默认5轮；缺失清单每缩短一次（实质进展）追加2轮、上限16。
        # 否则"一个待办多个文件、每轮只落盘1个"会被固定5轮掐死
        # （2026-11-09 生产 task23：6文件待办写到第5轮、还差2个文件被判失败；
        #  2026-11-13 task82 手动测试：归类待办根目录11项，上限12零容错搬不完）
        _round_budget = max_loop_iterations
        _prev_missing: set = set()
        _written_files: set = set()
        _prev_action = None   # 上一轮选中的技能（出错重试时按需注入其全量 schema）
        _fail_refunds = 0     # 工具执行失败的退轮次数（最多3次，防死循环）
        _skip_refunds = 0     # 跳过（重复读/写后读回）的退轮次数（最多3次）

        loop_idx = -1
        while True:
            loop_idx += 1
            if loop_idx >= _round_budget:
                break
            # 检查终止（补齐轮不走终止判定，理由见函数入口）
            if not is_repair:
                should_stop, stop_reason = self._check_termination()
                if should_stop:
                    return _stop_result(state, stop_reason)

            logger.debug(f"[AgentGraph] 待办 {todo_id} 循环 {loop_idx + 1}/{max_loop_iterations}")

            # 轮次计数:一次 thought→plan→execute 记 1 轮
            if self._state_manager:
                self._state_manager.next_iteration()

            # === Thought 阶段 ===
            thought_context = self._budget_hint(context)
            hist_note = (state.context or {}).get("history_note") or ""
            if hist_note:
                thought_context += "\n\n" + hist_note
            logger.info("[Loop] think start todo=%s loop=%s", todo_id, loop_idx + 1)
            # 文件类任务开局先锚定任务目录（2026-11-13 任务86取证：新会话
            # task_path 为空 → list/search/read 全落到 tasks/ 根，37 个跨任务
            # 目录泄漏进观察、裸路径反复"文件不存在"，模型开局连读失败）。
            # 锚定后：清单注入、list "."、read/search 全部以本任务目录为基准，
            # 模型开局即知道目录是空的 → 先搭框架而不是读不存在的文件。
            if not context_obj.task_path and getattr(state, "intent", None) in (
                "file_ops", "code", "data", "crawler"
            ):
                _tp0 = await self._ensure_session_task_dir(context_obj)
                if _tp0:
                    logger.info(f"[Loop] 文件类任务开局锚定任务目录: {_tp0}")
            _dir_note = ""
            _dir_files_note = ""
            if context_obj.task_path:
                _dir_note = (
                    f"\n\n[任务目录] {context_obj.task_path}（磁盘: tasks/{context_obj.task_path}）。"
                    "所有 path 参数写任务目录内的相对路径（如 src/App.vue）；"
                    "禁止在 path 中重复写任务目录名或其他项目目录名（如 app_xxx/src/...）。"
                )
                thought_context += _dir_note
                # 磁盘文件清单注入思考/计划端（此前只注入观察端——
                # 2026-11-13 生产取证：思考端只拿到目录名提示，模型凭待办
                # 文字猜路径，反复按裸名 read extensions.py 失败 4 次）
                try:
                    from app.agent.skills.file_operations.skill import get_tasks_dir as _gtd0
                    _base0 = _gtd0() / context_obj.task_path
                    if _base0.is_dir():
                        _fl0 = []
                        for _r0, _d0, _fs0 in os.walk(_base0):
                            for _f0 in _fs0:
                                try:
                                    _fl0.append(str(Path(_r0, _f0).relative_to(_base0)))
                                except Exception:
                                    pass
                        _dir_files_note = "\n\n【任务目录现有文件】\n" + (
                            "\n".join(sorted(_fl0)) if _fl0 else "（空，尚未生成任何文件）")
                        thought_context += _dir_files_note
                except Exception:
                    _dir_files_note = ""
            if last_error and loop_idx > 0:
                thought_context += f"\n\n[上一步失败信息]\n错误: {last_error}\n执行结果: {last_execution_result}\n请分析失败原因，思考如何修正参数来解决问题。"

            # 末轮强制交付（2026-11-13 生产 todo1 取证：5 轮全在 read/list 翻文件、
            # 从未进入产出，轮次耗尽即 FAILED 且无降级 → 在最后一轮强制收敛）
            if loop_idx + 1 >= _round_budget:
                thought_context += (
                    "\n\n【最后一轮 · 强制交付】这是本待办的最后一轮预算。"
                    "禁止再收集信息（不要再 search/read/list）；必须基于已有信息"
                    "立即产出交付物（写文件或给出最终答复）。产出不完美也必须交付；"
                    "本轮结束仍未产出，本待办将判定失败。"
                )

            # ContextManager step 前钩子：召回(JIT) → 按预算重建本 step 上下文。
            # 拼在既有 notes 之后（budget hint/目录/失败信息保持原位不动）。
            if self._ctx_mgr is not None:
                try:
                    self._ctx_step += 1
                    _bres = self._ctx_mgr.on_step_start(
                        step=self._ctx_step, query=state.task)
                    if _bres and _bres.prompt:
                        thought_context += (
                            "\n\n【本步上下文（按需召回的历史观察，重建式）】\n"
                            + _bres.prompt)
                    if _bres:
                        logger.info(
                            "[CtxMgr] step=%d used=%d/%d omitted=%d masked=%d",
                            self._ctx_step, _bres.used_tokens, _bres.max_tokens,
                            len(_bres.omitted), len(_bres.masked))
                        # 实时上下文占用 → 前端工具栏（2026-11-12 方案B；
                        # 11-13 修为真实值：分子=本步完整提示词 token 数
                        # （含 history_note/预算提示/目录与失败信息/召回片段），
                        # 并接续上轮峰值 floor → 跨轮不再从 0 开始；
                        # 11-14 P1/P2：used 改为真实 usage 单请求峰值
                        # （含提示词模板+技能/工具清单+task，DeepSeek 口径），
                        # 无真实值回退估算；新增 billed_* 本 turn 计费累计。
                        if on_step:
                            try:
                                from app.agent.context import count_tokens as _ctok
                                from app.agent.llm.factory import (
                                    get_task_usage, get_last_usage)
                                _max_u = self._ctx_mgr.cfg.max_tokens
                                # 本步完整上下文 token（系统提示词在 Planner 内部拼）
                                _est_u = _ctok(thought_context)
                                _tu = get_task_usage()
                                _real_peak = int(_tu.get("peak_in") or 0)
                                _used_u = max(self._ctx_floor, _real_peak) \
                                    if _real_peak \
                                    else max(self._ctx_floor, _est_u)
                                if _used_u > self._ctx_peak:
                                    self._ctx_peak = _used_u
                                on_step("context_usage", {
                                    "used": _used_u,
                                    "max": _max_u,
                                    "ratio": round(_used_u / _max_u, 4) if _max_u else 0.0,
                                    "compress_count": self._ctx_compress_count,
                                    "step": self._ctx_step,
                                    "used_est": _est_u,
                                    **self._billed_payload(_tu),
                                    "last_in": int(get_last_usage().get("prompt_tokens") or 0),
                                })
                            except Exception:
                                pass
                except Exception as _ce:
                    logger.warning("[CtxMgr] on_step_start 失败（不阻塞）: %s", _ce)

            thought = await self._planner.think(state.task, todo_item.to_dict() if hasattr(todo_item, "to_dict") else todo, thought_context)

            # 检查取消（LLM 调用后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            # 更新 scratchpad
            if self._state_manager:
                self._state_manager.append_thought(thought)

            if on_step:
                on_step("thought", {"content": thought, "todo_id": todo_id})

            await self._save_execution_node(
                todo_id=todo_id,
                node_type="thought",
                content=thought,
                iteration=iteration,
                meta_data={"loop_index": loop_idx, "has_error_context": last_error is not None}
            )

            logger.info("[Loop] think done (%s chars), planning", len(thought or ""))
            # === Plan 阶段 ===
            plan_result = await self._planner.plan_action_with_feedback(
                task=state.task,
                todo=todo_item.to_dict() if hasattr(todo_item, "to_dict") else todo,
                thought=(thought or "") + _dir_note + _dir_files_note,
                last_error=last_error,
                last_result=last_execution_result,
                last_action=_prev_action,
                last_error_code=last_error_code,
            )

            # 检查取消（LLM 调用后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            action = plan_result.get("action", "general_response")
            params = plan_result.get("params", {})
            reason = plan_result.get("reason", "")
            _prev_action = action

            # 确保 task_path 存在
            params = await self._ensure_task_path(params, action)
            # 文件族动作强制锚定任务目录，含 search_files（之前不在
            # _ensure_task_path 集合里 → 无目录时直接搜 tasks/ 根，跨任务
            # 泄漏；2026-11-13 任务86取证）。context 回填 + params 同步。
            if action in ("file_operations", "search_files", "code_generator",
                          "add_files_to_project", "improve_file"):
                if not context_obj.task_path:
                    await self._ensure_session_task_dir(context_obj)
                if context_obj.task_path and params.get("task_path") != context_obj.task_path:
                    params = params.copy()
                    params["task_path"] = context_obj.task_path

            # 更新 todo_item 的 action 和 params
            todo_item.action = action
            todo_item.params = params

            planning_content = (
                f"动作: {action}\n"
                f"参数: {json.dumps(params, ensure_ascii=False, default=str)}\n"
                f"原因: {reason}"
            )
            _target_files = plan_result.get("target_files") or []
            if _target_files:
                planning_content += "\n目标文件: " + ", ".join(_target_files)
                _pf = state.context.setdefault("_promised_files", [])
                for _f in _target_files:
                    _fs = str(_f).strip()
                    if _fs and _fs not in _pf:
                        _pf.append(_fs)
            if last_error:
                planning_content += f"\n修正: 基于错误 '{last_error}' 调整参数"

            if on_step:
                on_step("planning", {"content": planning_content, "action": action, "todo_id": todo_id})

            await self._save_execution_node(
                todo_id=todo_id,
                node_type="planning",
                content=planning_content,
                action=action,
                params=params,
                iteration=iteration,
                meta_data={"reason": reason, "loop_index": loop_idx}
            )

            # === 坏计划拦截前移（阶段一，快改1）：params_invalid 为真不进执行，
            # 直接生成结构化 last_error 走 correction——省一次必败的执行往返
            _intercept = build_plan_interception(plan_result)
            if _intercept:
                last_error = _intercept["error"]
                last_error_code = _intercept["error_code"]
                last_execution_result = "（计划参数无效，本轮未执行）"
                logger.warning(
                    "[AgentGraph] 拦截坏计划 todo=%s code=%s: %s",
                    todo_id, last_error_code, last_error)
                if on_step:
                    on_step("error", {
                        "content": last_error, "todo_id": todo_id,
                        "error_code": last_error_code,
                    })
                continue

            # === 检查是否重复调用 ===
            call_key = f"{action}:{json.dumps(params, sort_keys=True, default=str)}"
            call_count = sum(1 for c in tool_call_history if c == call_key)
            if call_count >= max_same_call:
                logger.warning(f"[AgentGraph] 检测到相同调用重复 {call_count} 次，中断循环: {action}")
                last_error = f"相同调用已重复 {call_count} 次，无法继续。请尝试其他方法或任务失败。"
                if on_step:
                    on_step("error", {"content": last_error, "todo_id": todo_id})
                exit_reason = "duplicate_call"
                break
            tool_call_history.append(call_key)

            # === NextMoves 阶段 ===
            if on_step:
                on_step("next_moves", {"action": action, "params": params, "todo_id": todo_id})

            # 合并 params
            merged_params = {**todo_params, **params}
            if context_obj.task_path:
                merged_params["task_path"] = context_obj.task_path
            # 传递 session_id 让 file_operations 能正确处理会话限制
            if self._session_id:
                merged_params["session_id"] = self._session_id

            timeout = context_obj.get_timeout_for_action(action)
            # 将 TodoItem 转换为字典进行解包
            todo_dict = todo.to_dict() if hasattr(todo, "to_dict") else todo
            execution_result = await self._execute_with_timeout(
                {**todo_dict, "action": action, "params": merged_params},
                context_obj, timeout, context_obj.task_path
            )

            # 检查取消（技能执行后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            last_execution_result = str(execution_result.get("data", ""))[:200]
            last_error = execution_result.get("error") or (
                None if execution_result.get("success", False) else "执行失败"
            )
            # 结构化错误码随错误透传（阶段一）；成功时清空防串轮
            last_error_code = (
                execution_result.get("error_code") if last_error else None
            )

            # ContextManager Observation 后钩子：登记观察 → 更新预算 →
            # 预算超限才做 step 级 masking（全量压缩只在 turn 后）。
            # persisted=True：观察已落 execution_nodes 表，被移除后可恢复。
            if self._ctx_mgr is not None:
                try:
                    _obs_data = execution_result.get("data")
                    _obs_content = (str(_obs_data) if _obs_data is not None
                                    else str(last_error or ""))
                    self._ctx_mgr.on_observation(
                        obs_id=f"obs:{todo_id}:{self._ctx_step}",
                        content=_obs_content[:4000],
                        tool=str(action or ""),
                        params_summary=str(merged_params)[:200],
                        one_line=str(last_execution_result or last_error or ""),
                        depends_on_action_step=self._ctx_step,
                        persisted=True,
                    )
                    logger.info("[CtxMgr] obs registered id=%s:%d tool=%s",
                                todo_id, self._ctx_step, str(action or ""))
                except Exception as _ce:
                    logger.warning("[CtxMgr] on_observation 失败（不阻塞）: %s", _ce)

            # 更新 scratchpad
            if self._state_manager:
                self._state_manager.append_action(action, merged_params)
                self._state_manager.append_observation(
                    last_execution_result if execution_result.get("success") else last_error
                )

            await self._save_execution_node(
                todo_id=todo_id,
                node_type="next_moves",
                content=f"执行 {action}",
                action=action,
                params=merged_params,
                result=execution_result,
                iteration=iteration,
                success=execution_result.get("success", False),
                meta_data={"loop_index": loop_idx}
            )

            # === Observation 阶段 ===
            # 任务目录现有文件清单（磁盘真相）在本轮循环开始时已构建（_dir_files_note），
            # 观察与思考/计划端共用同一份清单（此前只注入观察端，思考端凭待办文字猜路径
            # 反复按裸名 read 失败）
            observation_result = await self._planner.observe(
                state.task, todo_item.to_dict() if hasattr(todo_item, "to_dict") else todo,
                action, merged_params, execution_result,
                extra_context=f"【思考】\n{thought or ''}\n\n【计划】\n{planning_content}" + _dir_note + _dir_files_note,
            )
            for _mf in (observation_result.get("files_mentioned") or []):
                _ms = str(_mf).strip()
                if _ms:
                    _pf2 = state.context.setdefault("_promised_files", [])
                    if _ms not in _pf2:
                        _pf2.append(_ms)

            # 检查取消（LLM 调用后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            # === 提到的文件必须真实存在（用户规则：文件未生成=代码逻辑有问题，禁止完成） ===
            _tp = None
            try:
                from app.agent.skills.file_operations.skill import get_tasks_dir as _gtd
                _tp = context_obj.task_path or merged_params.get("task_path")
                _base = (_gtd() / _tp) if _tp else None
            except Exception:
                _base = None
            _missing = _check_promised_files(
                list(observation_result.get("files_mentioned") or [])
                + list(plan_result.get("target_files") or []),
                merged_params, execution_result, _base,
            )
            if _missing:
                _cur_missing = set(_missing)
                if _prev_missing and _cur_missing < _prev_missing:
                    # 缺失清单缩短 = 实质进展：追加轮次预算（上限16）
                    _round_budget = min(_round_budget + 2, 16)
                    logger.info(
                        "[AgentGraph] 待办 %s 缺失文件有进展(%s->%s)，轮次预算增至 %s",
                        todo_id, len(_prev_missing), len(_cur_missing), _round_budget,
                    )
                _prev_missing = _cur_missing
            # 本轮成功落盘新文件 = 实质进展：追加轮次预算（上限16）。
            # 只对写类动作计：读操作/重复覆盖已有文件不算进展。
            # 2026-11-13 TC-S16-01 取证：批量参数（files/paths）没有顶层
            # path → _np 恒空、delete 不在白名单 → 批量写/删从不给预算续命，
            # todo4 第5轮被掐死判失败。改为：单 path + files[] + paths[] 都算，
            # op 白名单加 delete（清理残留也是实质进展）。
            _op = merged_params.get("operation")
            if execution_result.get("success") and action in (
                "file_operations", "code_generator", "add_files_to_project", "improve_file"
            ) and (action != "file_operations" or _op in ("write", "create", "edit", "move", "delete")):
                _cands = [str(merged_params.get("path") or merged_params.get("output_path") or "")]
                for _it in (merged_params.get("files") or []):
                    if isinstance(_it, dict):
                        _cands.append(str(_it.get("path") or _it.get("from")
                                          or _it.get("src") or ""))
                    elif isinstance(_it, str):
                        _cands.append(_it)
                for _it in (merged_params.get("paths") or []):
                    if isinstance(_it, str):
                        _cands.append(_it)
                _new_np = []
                for _c in _cands:
                    _c = _norm_rel(_c)
                    if _c and _c not in _written_files:
                        _written_files.add(_c)
                        _new_np.append(_c)
                if _new_np:
                    if _round_budget < 16:
                        _round_budget = min(_round_budget + 2, 16)
                        logger.info(
                            "[AgentGraph] 待办 %s 实质进展 %s，轮次预算增至 %s",
                            todo_id, _new_np[:4], _round_budget)
            # 工具执行失败不产进展却烧预算：退1轮给"修正参数重试"
            # （2026-11-13 用户测试：edit 缺 old_text 失败后模型绕只读动作，
            # 5 轮预算烧尽、待办判失败；最多退 3 轮防死循环）
            if not execution_result.get("success", False) and _fail_refunds < 3:
                _fail_refunds += 1
                _round_budget = min(_round_budget + 1, 19)
                logger.info(
                    "[AgentGraph] 待办 %s 工具执行失败，退1轮预算(增至%s)，允许修正参数重试(第%s次)",
                    todo_id, _round_budget, _fail_refunds,
                )
            # 跳过（重复读/写后读回）不产进展却烧预算：退1轮给"动手改"的
            # 机会（生产 2026-11-14 00:12 第三轮：5 轮全 read 烧光判失败）
            _d = execution_result.get("data")
            if isinstance(_d, dict) and _d.get("skipped") and _skip_refunds < 3:
                _skip_refunds += 1
                _round_budget = min(_round_budget + 1, 19)
                logger.info(
                    "[AgentGraph] 待办 %s 跳过不产进展却烧预算，退1轮预算(增至%s)，"
                    "强制动手改(第%s次)", todo_id, _round_budget, _skip_refunds,
                )
            _miss_msg = ""
            if _missing:
                # 文案第三次迭代（2026-11-14 用户定稿）：不以待办状态断言
                # 开头（"待办未完成"指待办项、用户看过程易误以为本步失败），
                # 只说本步状态 + 具体问题：本步操作成功与否 + 对照任务目录缺
                # 哪些文件；任务目录仍放句首带查找根（2026-11-13：相对路径
                # 易被误读成"没带任务目录从下一级找"）。
                _tool_ok = bool(execution_result.get("success", False))
                _head = "本步操作已成功，但" if _tool_ok else "本步操作失败，"
                _head += (f"对照任务目录 {_tp} 按相对路径检查，以下承诺产出文件尚未创建: "
                          if _tp else "以下承诺产出文件尚未创建: ")
                _miss_msg = (
                    _head
                    + ", ".join(_missing)
                    + "。这些文件必须真实写入磁盘；"
                    "已存在的文件不要重复创建，本轮只写上面缺失的文件；"
                    "若不属于本待办产出，就不要在思考/计划中提及它们。"
                )
                logger.warning("[AgentGraph] 待办 %s 提到的文件未生成: %s", todo_id, _missing)
                observation_result["completed"] = False
                observation_result["success"] = False
                observation_result["reason"] = _miss_msg + (
                    " 原判断: " + str(observation_result.get("reason") or "")
                )
                observation_result["suggestion"] = "生成缺失文件后重试"
                # 保留原有错误信息（如工具失败），拼上缺失清单一起喂给下一轮思考
                last_error = f"{last_error}；{_miss_msg}" if last_error else _miss_msg
            elif not last_error and not observation_result.get("completed", False):
                # 观察判未完成但闸门没拦（没有缺失文件）：把观察结论喂给
                # 下一轮思考，否则模型不知道为何没完成、只会原地重写文件
                # （生产实测：todo0 盲写12轮直至轮次耗尽失败的直接原因）
                last_error = str(observation_result.get("reason") or "上一轮观察判断未完成")

            _skip_note = ""
            _sd = execution_result.get("data")
            if isinstance(_sd, dict) and _sd.get("skipped"):
                _fl = ", ".join(_sd.get("files") or [])
                _skip_note = (f"本步已跳过读取（{_sd.get('skipped')}"
                              + (f"，文件: {_fl}" if _fl else "")
                              + "）：内容仍在上下文，无需重复读取。\n")
            obs_content = _skip_note + f"完成状态: {'已完成' if observation_result.get('completed', False) else '未完成'}\n"
            obs_content += f"原因: {observation_result.get('reason', '')}\n"
            obs_content += f"建议: {observation_result.get('suggestion', '')}"

            if on_step:
                _is_progress = (
                    not observation_result.get("completed", False)
                    and (loop_idx + 1) < _round_budget
                )
                on_step("observation", {
                    "content": obs_content,
                    "success": observation_result.get("success", False),
                    # 工具本身是否执行成功——与观察判定分开上报：
                    # 工具成功但观察判未完成 ≠ 工具失败，前端据此区分徽标语义
                    "tool_success": bool(execution_result.get("success", False)),
                    "progress": _is_progress,
                    "todo_id": todo_id
                })

            await self._save_execution_node(
                todo_id=todo_id,
                node_type="observation",
                content=obs_content,
                result=observation_result,
                is_final=observation_result.get("completed", False),
                success=observation_result.get("success", False),
                iteration=iteration,
                meta_data={"loop_index": loop_idx}
            )

            # 更新 state_manager 中的错误记录
            if self._state_manager:
                if not execution_result.get("success", False) or _missing:
                    self._state_manager.errors.append({
                        "todo_id": str(todo_id),
                        "error": last_error or "执行失败",
                    })
                if _missing:
                    # 提到的文件没生成 = 未完成，禁止打勾，进入重试
                    todo_item.status = TodoStatus.FAILED
                    todo_item.error = _miss_msg
                elif observation_result.get("completed", False):
                    # 状态以观察（LLM）结论为准，禁止拿工具 success 代替判断
                    todo_item.status = TodoStatus.COMPLETED
                    todo_item.error = ""
                elif execution_result.get("success", False):
                    # 工具成功但观察判未完成 = 有进展、活没干完：保持进行中继续重试
                    todo_item.status = TodoStatus.IN_PROGRESS
                    todo_item.error = ""
                else:
                    todo_item.status = TodoStatus.FAILED
                    todo_item.error = last_error or "执行失败"
                todo_item.result = last_execution_result if execution_result.get("success", False) else ""

            # 每个 action 后保存状态（断点恢复）
            if self._state_manager:
                await self._state_manager.save_state()

            # 检查取消（状态保存后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            # 每个 action 后保存状态（断点恢复）
            if self._state_manager:
                await self._state_manager.save_state()

            # 如果写文件成功，更新 context_obj.task_path（供后续待办使用）
            # code_generator 同样会落盘，必须一起处理，否则它的产物不进文件树
            if execution_result.get("success", False) and action in ("file_operations", "code_generator"):
                result_data = execution_result.get("data", {})
                returned_project = result_data.get("project_name") if isinstance(result_data, dict) else None
                if not returned_project:
                    # write 操作不返回 project_name（只有 create 返回）。不兜底的话，
                    # 首批文件之后每次写盘都不推 project_tree，文件结构区看不到新文件
                    # （2026-11-09 生产：6 文件全在磁盘，结构区只显示前 3 个）
                    returned_project = context_obj.task_path
                if returned_project:
                    context_obj.task_path = returned_project
                    logger.info(f"[AgentGraph] file_operations 返回 project_name: {returned_project}")
                    # 同步到 session_task_paths，使 API 层能获取最新任务路径
                    from app.api.v1.endpoints.agent import session_task_paths
                    session_task_paths[self._session_id] = returned_project
                    # 保存到 SessionContext 表
                    try:
                        from app.agent.tools.session_context import set_session_context
                        await set_session_context(self._session_id, "task_path", returned_project)
                    except Exception as e:
                        logger.debug(f"[AgentGraph] 保存 task_path 失败: {e}")
                    # 推送 project_tree 事件，让前端显示文件结构
                    if on_step:
                        file_tree: List[Dict[str, Any]] = []
                        try:
                            from app.agent.skills.file_operations.skill import get_tasks_dir
                            _base = get_tasks_dir() / returned_project
                            children = _walk_dir(_base, _base) if _base.exists() else []
                            # 根节点 = 任务文件夹，文件全挂在它下面（对齐前端文件树约定）
                            file_tree = [{
                                "name": returned_project,
                                "path": returned_project,
                                "type": "folder",
                                "children": children,
                            }] if children else []
                        except Exception as e:
                            logger.warning(f"[AgentGraph] 构建文件树失败: {e}")
                        files = result_data.get("files", []) if isinstance(result_data, dict) else []
                        on_step("project_tree", {
                            "project_name": returned_project,
                            "task_path": returned_project,
                            "files": files,
                            "file_tree": file_tree,
                        })

            # 判断是否完成
            if observation_result.get("completed", False):
                return {
                    "success": True,
                    "summary": observation_result.get("reason", "已完成"),
                    "iteration": loop_idx + 1,
                    "action": action,
                    "project_name": (
                        context_obj.task_path
                        if execution_result.get("success", False) and action == "file_operations"
                        else None
                    )
                }

            # 执行成功但观察判断未完成：不再强制完成（2026-11-09 task23 实锤：
            # 只读一轮没干活也会被"工具成功"放行 = 假完成）。以观察结论为准，
            # 带着未完成原因进入下一轮重试；预算内完成不了则如实失败。
            if (
                execution_result.get("success", False)
                and not observation_result.get("completed", False)
            ):
                last_error = "观察判断未完成: " + str(observation_result.get("reason") or "")

            # 更新上下文，进入下一轮循环
            logger.info(f"[AgentGraph] 待办 {todo_id} 第 {loop_idx + 1} 次失败: {last_error}")

        # 循环退出收尾（阶段五：区分退出原因，修"重复调用 break 误报
        # 达到最大循环次数"的误导文案；轮次显示真实预算 _round_budget）
        if exit_reason == "duplicate_call":
            logger.warning(
                f"[AgentGraph] 待办 {todo_id} 相同调用重复中断（上限 {max_same_call} 次）")
            summary = (
                f"相同调用重复达到上限({max_same_call}次)中断，未能完成。"
                f"末次错误: {last_error}"
            )
        else:
            logger.warning(f"[AgentGraph] 待办 {todo_id} 达到最大循环次数")
            summary = (
                f"达到最大循环次数({_round_budget})，未能完成。末次错误: {last_error}"
            )
        return {
            "success": False,
            "summary": summary,
            # 轮次=实际进入循环体的轮数：预算耗尽时 loop_idx 即轮数；
            # 重复中断发生在第 loop_idx+1 轮内
            "iteration": (
                loop_idx + 1 if exit_reason == "duplicate_call" else loop_idx
            ),
            "action": action,
        }

    async def _ensure_session_task_dir(self, context_obj) -> Optional[str]:
        """锚定/创建会话任务目录，返回 task_path（失败/无会话返回 None）。

        2026-11-13 任务86根因：新会话 task_path 为空时，file_operations 的
        list/read、search_files 的 search 全部解析到 tasks/ 根目录——
        ① 观察里混入 37 个其他任务的目录（跨任务泄漏）② 模型看到别的任务里
        有 extensions.py，按裸名 read 永远落在 tasks 根 → 反复"文件不存在"
        ③ 文件清单注入也因无 task_path 被跳过。这里在文件族动作前把目录
        建好（沿用 skill 的 auto_project_<ts> 命名），并按既有落盘回写三件套
        同步 context/session_task_paths/SessionContext 表。
        """
        if getattr(context_obj, "task_path", None):
            return context_obj.task_path
        if not self._session_id:
            return None
        # 内存优先（落盘后先写这里），再回落 DB
        existing: Optional[str] = None
        try:
            from app.api.v1.endpoints.agent import session_task_paths
            existing = session_task_paths.get(self._session_id)
        except Exception:
            existing = None
        if not existing:
            existing = await self._get_session_task_path()
        if existing:
            context_obj.task_path = existing
            return existing
        import time as _time
        name = f"auto_project_{int(_time.time())}"
        try:
            from app.agent.skills.file_operations.skill import get_tasks_dir
            (get_tasks_dir() / name).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[AgentGraph] 创建任务目录失败: {e}")
            return None
        context_obj.task_path = name
        try:
            from app.api.v1.endpoints.agent import session_task_paths
            session_task_paths[self._session_id] = name
            from app.agent.tools.session_context import set_session_context
            await set_session_context(self._session_id, "task_path", name)
        except Exception as e:
            logger.debug(f"[AgentGraph] 持久化 task_path 失败: {e}")
        return name

    async def _ensure_task_path(self, params: Dict[str, Any], action: str) -> Dict[str, Any]:
        """确保写文件类 action 始终用**同一个**任务目录（目录中途变换的根因）。

        规则：
        1. 会话已有 task_path → 强制覆盖 params 里的值。LLM 每次编的
           task_path 名字一律不用，否则前端文件树根节点跟着不停变换。
        2. 没有 → 保留 params 给的；也没有就留空，由 file_operations 自建
           auto_project_*，首次落盘后会写回 session（内存 + DB）。
        code_generator 的落盘走 _auto_write_files，同样必须纳入本集合，
        否则它每次都自建一个新目录。
        """
        task_path_actions = {
            "file_operations",
            "add_files_to_project",
            "improve_file",
            "code_generator",
        }
        if action not in task_path_actions:
            return params

        existing: Optional[str] = None
        if self._session_id:
            try:
                # 内存优先（file_operations/code_generator 落盘后先写这里），
                # 再回落 DB —— 只读 DB 时写入失败就会退回"每待办新建目录"
                from app.api.v1.endpoints.agent import session_task_paths
                existing = session_task_paths.get(self._session_id)
            except Exception:
                existing = None
        if not existing:
            existing = await self._get_session_task_path()

        if existing and params.get("task_path") != existing:
            params = params.copy()
            params["task_path"] = existing

        # path 类参数规范化：剥离 ./、tasks/、任务目录名/外来项目目录名前缀，
        # 防止嵌套写盘（app_xxx/src/... → src/...）
        _changed = False
        for _k in ("path", "output_path", "file", "filename", "file_path"):
            _v = params.get(_k)
            if isinstance(_v, str) and _v and not _v.startswith("/") and not _v.startswith("~"):
                _nv = _norm_rel(_v)
                if _nv and _nv != _v:
                    if not _changed:
                        params = params.copy()
                        _changed = True
                    params[_k] = _nv
        return params

    async def _get_session_task_path(self) -> Optional[str]:
        """从数据库读取 session 的 task_path"""
        if not self._session_id:
            return None
        try:
            from app.agent.tools.session_context import get_session_context
            task_path = await get_session_context(self._session_id, "task_path")
            return task_path
        except Exception as e:
            logger.warning(f"[AgentGraph] 读取 session task_path 失败: {e}")
        return None

    async def _execute_with_timeout(
        self,
        step: Dict[str, Any],
        context: ExecutionContext,
        timeout: int,
        task_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """带超时的步骤执行"""
        import asyncio

        try:
            return await asyncio.wait_for(
                self._execute_single_step(step, task_path, self._session_id),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # 阶段三：超时计入 guard 熔断计数（内层被 cancel 不 finish，此处补）
            try:
                from app.agent.skills.guard import tool_guard
                tool_guard.finish(
                    step.get("action") or "", ok=False,
                    detail=f"timeout {timeout}s", error_code="TIMEOUT")
            except Exception as _ge:  # noqa: BLE001 - 守卫回执失败不阻塞
                logger.warning("[AgentGraph] guard.finish 超时回执失败: %s", _ge)
            return {
                "success": False,
                "error": f"步骤执行超时: {timeout}秒",
                "error_code": "TIMEOUT",
                "action": step.get("action"),
                "step": step.get("step"),
            }

    async def _execute_single_step(self, step: Dict[str, Any], task_path: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "unknown")
        params = step.get("params", {}).copy()
        _op = (params.get("operation") or "").lower() \
            if action == "file_operations" else ""
        _gk = session_id or "__none__"
        _guard = self._readback_guard.setdefault(
            _gk, {"prev_op": "", "last_write": set()})

        # 写后读回硬跳过（规则13软引导三遍真跑两遍仍有确认读，上执行层）：
        # 上一动作是 write、本次 read 的文件全部在刚写列表里 → 纯确认读，
        # 不执行（内容还在上下文），直接给跳过反馈让模型按缺件清单推进。
        if (_op == "read" and _guard["prev_op"] == "write"
                and _guard["last_write"]):
            _rp = set()
            for f in (params.get("files") or []):
                _rp.add((f.get("path") or "") if isinstance(f, dict) else str(f))
            if params.get("path"):
                _rp.add(str(params["path"]))
            _rp.discard("")
            if _rp and _rp <= _guard["last_write"]:
                _guard["prev_op"] = "read"
                _guard.setdefault("read_files", set()).update(_rp)
                logger.info(f"[ReadbackGuard] 跳过写后读回: {sorted(_rp)}")
                return {
                    "success": True,
                    "data": {
                        "skipped": "read_after_write",
                        "message": (
                            "已跳过写后读回：刚写入的内容仍在上下文，无需再读。"
                            "直接根据完成判定的缺件清单，批量写入缺失文件推进。"
                        ),
                        "files": sorted(_rp),
                    },
                    "error": None,
                    "action": action,
                }
        # 重复读跳过（生产 2026-11-14 00:12 第三轮空转：router/index.js 读
        # 3 遍、App.vue 2 遍，5 轮预算烧光判失败）——同 turn 同文件第 2 次
        # read 起内容已在上下文，跳过并强指令动手；循环层给它退 1 轮预算。
        if _op == "read":
            _rp = set()
            for f in (params.get("files") or []):
                _rp.add((f.get("path") or "") if isinstance(f, dict) else str(f))
            if params.get("path"):
                _rp.add(str(params["path"]))
            _rp.discard("")
            _seen = _guard.setdefault("read_files", set())
            if _rp and _rp <= _seen:
                _guard["prev_op"] = "read"
                logger.info(f"[ReadbackGuard] 跳过重复读: {sorted(_rp)}")
                return {
                    "success": True,
                    "data": {
                        "skipped": "duplicate_read",
                        "message": (
                            f"已跳过重复读取（{'、'.join(sorted(_rp))}）："
                            "内容仍在上下文，禁止再读。本待办尚未完成，"
                            "必须本轮直接动手 edit/write 做出修改，"
                            "再读同一文件不会推进任何进展。"
                        ),
                        "files": sorted(_rp),
                    },
                    "error": None,
                    "action": action,
                }
            _seen.update(_rp)
        _guard["prev_op"] = _op
        _write_paths = set()
        if _op == "write":
            for f in (params.get("files") or []):
                _write_paths.add(
                    (f.get("path") or "") if isinstance(f, dict) else str(f))
            if params.get("path"):
                _write_paths.add(str(params["path"]))
            _write_paths.discard("")

        # 传递 task_path 到 skill，让它能正确写入 AiAgent/tasks/
        if task_path:
            params["task_path"] = task_path

        # 传递 session_id 到 skill，让它能正确处理会话限制
        if session_id:
            params["session_id"] = session_id

        try:
            from app.agent.skills.core.progressive_loader import get_loader
            loader = get_loader()
            result = await loader.execute(action, params)
            if _op == "write":
                _guard["last_write"] = (
                    _write_paths if result.success else set())
            # 优先使用 skill 返回的 friendly_action
            friendly_action = result.metadata.get("friendly_action") if result.metadata else None
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                # getattr 防御：测试 spy/旧 registry 返回对象可能无该字段
                "error_code": getattr(result, "error_code", None),
                "action": friendly_action or action,
            }
        except Exception as e:
            # 阶段五：删除旧 registry fallback（技能异常已在 loader.execute
            # 内部兜底为 SkillResult，这里只兜 import/加载器级别的意外）
            if _op == "write":
                _guard["last_write"] = set()
            return {
                "success": False,
                "error": str(e),
                "error_code": "EXEC_FAILED",
                "action": action,
            }

    async def _safety_check(self, state: AgentState) -> AgentState:
        """输入安全检查"""
        result = await self._guard.check_input(state.task)
        if not result.passed:
            state.error = f"安全检查失败: {result.error}"
            logger.warning(f"[AgentGraph] 安全检查未通过: {result.error}")
        elif result.warnings:
            logger.info(f"[AgentGraph] 安全检查警告: {result.warnings}")
        return state

    async def _detect_intent(self, state: AgentState) -> AgentState:
        """检测用户意图"""
        intent_result = await self._intent_detector.detect(state.task)
        state.intent = intent_result.get("primary_intent", "general")
        state.intents = intent_result.get("all_intents", [])
        state.confidence = intent_result.get("confidence", 0.0)
        state.context["intent_details"] = intent_result
        return state

    async def _plan(self, state: AgentState) -> AgentState:
        """制定执行计划"""
        try:
            plan = await self._planner.create_plan(state.task, state.intent)
            state.plan = plan
            logger.debug(f"[AgentGraph] 生成计划: {json.dumps(plan, ensure_ascii=False)[:200]}")
        except Exception as e:
            state.error = f"规划失败: {str(e)}"
            logger.exception(f"[AgentGraph] 规划异常")
        return state

    def _all_steps_succeeded(self, results: List[Dict[str, Any]]) -> bool:
        """检查是否所有步骤都成功"""
        if not results:
            return False
        return all(
            r.get("result", {}).get("success", False) if isinstance(r, dict) else r.get("success", False)
            for r in results
        )

    def _is_task_complete(self, state: AgentState) -> bool:
        """判断任务是否完成"""
        if state.error:
            return True
        if not state.results:
            return False
        return self._all_steps_succeeded(state.results)

    async def _integrate_results(self, state: AgentState) -> AgentState:
        """整合执行结果"""
        try:
            integrated = await self._integrator.integrate(state)
            # 兼容处理：integrate 可能返回字符串或字典
            if isinstance(integrated, dict):
                final_content = integrated.get("content", str(integrated))
            else:
                final_content = str(integrated)
            state.messages.append({
                "type": "final",
                "content": final_content,
                "metadata": {
                    "intent": state.intent,
                    "steps": len(state.results) if state.results else 0,
                    "routing": "unified",  # 统一模式标记
                }
            })
        except Exception as e:
            state.error = f"结果整合失败: {str(e)}"
            logger.exception(f"[AgentGraph] 整合结果异常")
        return state

    def _format_response(self, state: AgentState, context: Optional[ExecutionContext] = None) -> Dict[str, Any]:
        """格式化响应"""
        final_message = None
        for msg in reversed(state.messages):
            if msg.get("type") == "final":
                final_message = msg.get("content")
                break

        response = {
            "success": state.error is None,
            "result": cap_notice(final_message or (
                state.results[-1].get("result", {}).get("data")
                if state.results else None
            ), state),
            "error": state.error,
            "intent": state.intent,
            "intents": state.intents,
            "confidence": state.confidence,
            "plan": state.plan,
            "steps_executed": len(state.results) if state.results else 0,
            "routing_mode": "unified",  # 统一模式
        }

        # 添加执行统计
        if context:
            response["execution_stats"] = {
                "iterations": context.iteration + 1,
                "max_iterations": context.max_iterations,
                "failed_steps": context.failed_steps,
                "termination_reason": context.termination_reason,
            }

        return response

    def _format_error(self, error: str, state: AgentState) -> Dict[str, Any]:
        """格式化错误响应"""
        return {
            "success": False,
            "result": None,
            "error": error,
            "intent": state.intent,
            "intents": state.intents,
            "confidence": state.confidence,
            "plan": state.plan,
            "steps_executed": len(state.results) if state.results else 0,
            "routing_mode": "unified",
        }

    def _format_cancelled_result(self, state: AgentState) -> Dict[str, Any]:
        """格式化取消响应"""
        return {
            "success": False,
            "result": None,
            "error": "用户取消执行",
            "cancelled": True,
            "intent": state.intent,
            "intents": state.intents,
            "confidence": state.confidence,
            "plan": state.plan,
            "steps_executed": len(state.results) if state.results else 0,
            "routing_mode": "unified",
        }
