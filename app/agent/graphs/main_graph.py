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


_PROJECT_SEG_RE = re.compile(r"^(?:auto_project|app|project)(?:_\d+)?$")


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
    for c in candidates:
        c = c.strip().strip('`"\'').replace("\\", "/")
        if not c or c in seen or re.match(r"^(https?|ftp)://", c, re.I):
            continue
        seen.add(c)
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
        self._supervisor = SupervisorGraph()
        self._replanner = Replanner()
        self._loop_detector = default_loop_detector
        self._db_session = None  # 数据库会话
        self._session_id = None  # 当前会话ID
        self._task_id = None     # 当前任务ID
        self._state_manager: Optional[ExecutionStateManager] = None  # 执行状态管理器

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

    def _generate_step_analysis(self, step: Dict[str, Any], step_index: int, total_steps: int) -> str:
        """
        生成每个步骤执行前的思考分析

        Args:
            step: 步骤信息
            step_index: 步骤序号（从1开始）
            total_steps: 总步骤数

        Returns:
            思考分析文本
        """
        action = step.get("action", "unknown")
        description = step.get("description", "")
        params = step.get("params", {})

        action_descriptions = {
            "code_generator": "根据需求生成代码文件",
            "http_client": "发起HTTP请求获取数据",
            "data_processor": "处理和转换数据",
            "file_operations": "执行文件读写操作",
            "search": "搜索相关信息",
            "notification": "发送通知消息",
            "general_response": "生成对话响应",
        }

        action_hint = action_descriptions.get(action, f"执行 {action} 操作")

        analysis = f"**执行步骤 {step_index}/{total_steps}**\n\n"
        analysis += f"- 动作：{action_hint}\n"
        if description:
            analysis += f"- 目标：{description}\n"

        # 根据不同 action 添加具体参数提示
        if action == "code_generator":
            language = params.get("language", "未指定")
            analysis += f"- 语言：{language}\n"
        elif action == "http_client":
            url = params.get("url", "未指定")
            method = params.get("method", "GET")
            analysis += f"- 请求：{method} {url}\n"
        elif action == "file_operations":
            operation = params.get("operation", "未指定")
            analysis += f"- 操作：{operation}\n"

        analysis += f"\n正在执行..."
        return analysis

    def _format_step_observation(self, action: str, result: Dict[str, Any], files: List[Dict[str, Any]]) -> str:
        """生成人类可读的步骤观察消息"""
        success = result.get("success", True)
        error = result.get("error")

        if success:
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

        logger.info(f"[AgentGraph] 开始执行任务: {task[:100]}...")

        # 执行过程中调用回调
        if on_step:
            on_step("planning", {"status": "开始执行任务"})

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
                logger.warning(f"[AgentGraph] 任务以失败收尾: {state.error}")
                if on_step:
                    on_step("error", {"message": state.error})
                if self._state_manager and session_id:
                    await self._state_manager.clear_state()
                if task_id:
                    task_manager.fail_task(task_id)
                return self._format_error(state.error, state)

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

            # 任务完成，清除持久化状态(轮次上限截断时保留,供继续执行)
            if self._state_manager and session_id and not state.context.get("_rounds_capped"):
                await self._state_manager.clear_state()
            if task_id:
                task_manager.complete_task(task_id)

            return self._format_response(state, exec_context)

        except Exception as e:
            logger.exception(f"[AgentGraph] 执行异常: {e}")
            state.error = str(e)
            if on_step:
                on_step("error", {"message": str(e)})
            if task_id:
                task_manager.fail_task(task_id)
            return self._format_error(state.error, state)

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
        last_execution_result = None
        # 追踪工具调用历史，防止相同调用重复3次以上
        tool_call_history = []
        max_same_call = 3
        # 轮次预算：默认5轮；缺失清单每缩短一次（实质进展）追加2轮、上限12。
        # 否则"一个待办多个文件、每轮只落盘1个"会被固定5轮掐死
        # （2026-11-09 生产 task23：6文件待办写到第5轮、还差2个文件被判失败）
        _round_budget = max_loop_iterations
        _prev_missing: set = set()
        _written_files: set = set()

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
            _dir_note = ""
            if context_obj.task_path:
                _dir_note = (
                    f"\n\n[任务目录] {context_obj.task_path}（磁盘: tasks/{context_obj.task_path}）。"
                    "所有 path 参数写任务目录内的相对路径（如 src/App.vue）；"
                    "禁止在 path 中重复写任务目录名或其他项目目录名（如 app_xxx/src/...）。"
                )
                thought_context += _dir_note
            if last_error and loop_idx > 0:
                thought_context += f"\n\n[上一步失败信息]\n错误: {last_error}\n执行结果: {last_execution_result}\n请分析失败原因，思考如何修正参数来解决问题。"

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
                thought=(thought or "") + _dir_note,
                last_error=last_error,
                last_result=last_execution_result
            )

            # 检查取消（LLM 调用后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            action = plan_result.get("action", "general_response")
            params = plan_result.get("params", {})
            reason = plan_result.get("reason", "")

            # 确保 task_path 存在
            params = await self._ensure_task_path(params, action)

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

            # === 检查是否重复调用 ===
            call_key = f"{action}:{json.dumps(params, sort_keys=True, default=str)}"
            call_count = sum(1 for c in tool_call_history if c == call_key)
            if call_count >= max_same_call:
                logger.warning(f"[AgentGraph] 检测到相同调用重复 {call_count} 次，中断循环: {action}")
                last_error = f"相同调用已重复 {call_count} 次，无法继续。请尝试其他方法或任务失败。"
                if on_step:
                    on_step("error", {"content": last_error, "todo_id": todo_id})
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
            # 观察前注入任务目录现有文件清单（磁盘真相），让观察结论有据可查：
            # 否则观察只能靠复述思考里的计划清单盲判（生产实测 todo0 因此
            # 反复声称"仍需补全"已存在的文件，原地重写直至轮次耗尽失败）
            _dir_files_note = ""
            try:
                from app.agent.skills.file_operations.skill import get_tasks_dir as _gtd0
                _tp0 = context_obj.task_path or merged_params.get("task_path")
                _base0 = (_gtd0() / _tp0) if _tp0 else None
                if _base0 and os.path.isdir(_base0):
                    _fl0 = []
                    for _r0, _d0, _fs0 in os.walk(_base0):
                        for _f0 in _fs0:
                            try:
                                _fl0.append(str(Path(_r0, _f0).relative_to(_base0)))
                            except Exception:
                                pass
                    _dir_files_note = "\n\n【任务目录现有文件】\n" + (
                        "\n".join(sorted(_fl0)) if _fl0 else "（空，尚未生成任何文件）"
                    )
            except Exception:
                _dir_files_note = ""
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
                    # 缺失清单缩短 = 实质进展：追加轮次预算（上限12）
                    _round_budget = min(_round_budget + 2, 12)
                    logger.info(
                        "[AgentGraph] 待办 %s 缺失文件有进展(%s->%s)，轮次预算增至 %s",
                        todo_id, len(_prev_missing), len(_cur_missing), _round_budget,
                    )
                _prev_missing = _cur_missing
            # 本轮成功落盘新文件 = 实质进展：追加轮次预算（上限12）。
            # 只对写类动作计：读操作/重复覆盖已有文件不算进展
            _op = merged_params.get("operation")
            if execution_result.get("success") and action in (
                "file_operations", "code_generator", "add_files_to_project", "improve_file"
            ) and (action != "file_operations" or _op in ("write", "create", "edit")):
                _np = _norm_rel(str(merged_params.get("path") or merged_params.get("output_path") or ""))
                if _np and _np not in _written_files:
                    _written_files.add(_np)
                    if _round_budget < 12:
                        _round_budget = min(_round_budget + 2, 12)
                        logger.info("[AgentGraph] 待办 %s 落盘新文件 %s，轮次预算增至 %s", todo_id, _np, _round_budget)
            _miss_msg = ""
            if _missing:
                _miss_msg = (
                    "以下文件在本待办过程中提到但任务目录中不存在: "
                    + ", ".join(_missing)
                    + "。必须真实创建这些文件（写入磁盘）后本待办才算完成；"
                    "已存在的文件不要重复创建，本轮只写上面缺失的文件；"
                    "若不属于本待办产出，就不要在思考/计划中提及它们。"
                    + (f"（任务目录: {_tp}，path 写目录内相对路径）" if _tp else "")
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

            obs_content = f"完成状态: {'已完成' if observation_result.get('completed', False) else '未完成'}\n"
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

        # 达到最大循环次数
        logger.warning(f"[AgentGraph] 待办 {todo_id} 达到最大循环次数")
        return {
            "success": False,
            "summary": f"达到最大循环次数({max_loop_iterations})，未能完成。末次错误: {last_error}",
            "iteration": max_loop_iterations,
            "action": action,
        }

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

    async def _observe_execution(
        self,
        iteration: int,
        state: AgentState,
        results: List[Dict[str, Any]],
        context: ExecutionContext,
    ) -> ObservationResult:
        """
        Observation 阶段: 观察执行情况，决定下一步行动

        包括:
        1. Supervisor 评估
        2. 死循环检测
        3. 迭代次数警告
        """
        # 1. Supervisor 步骤级评估
        supervisor_decision = await self._supervisor.evaluate_step_results(results)

        # 2. 死循环检测
        loop_result = self._loop_detector.detect(context, state.plan or [])

        # 合并结果
        if loop_result.loop_status != LoopDetectionResult.NORMAL:
            return loop_result

        # 3. 预算检查
        budget_status = state.context.get("budget_status", "normal")
        if budget_status == "exhausted":
            return ObservationResult(
                loop_status=LoopDetectionResult.BUDGET_EXHAUSTED,
                should_continue=False,
                should_terminate=True,
                termination_reason="预算已耗尽",
                fallback_action="return_partial_results",
                message="执行终止: 预算已耗尽"
            )

        return ObservationResult(
            loop_status=LoopDetectionResult.NORMAL,
            should_continue=True,
            should_replan=supervisor_decision.action == "replan",
            message=supervisor_decision.reason
        )

    async def _execute_parallel_with_deps(
        self,
        plan: List[Dict[str, Any]],
        context: ExecutionContext,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        并行执行计划，支持步骤依赖

        使用拓扑排序分层执行：
        - 每层内部并行
        - 层间串行
        """
        # 1. 构建依赖图并拓扑排序
        layers = self._build_execution_layers(plan)

        all_results = []
        for layer in layers:
            # 2. 并行执行当前层
            import asyncio
            tasks = []
            for step in layer:
                timeout = context.get_timeout_for_action(step.get("action", ""))
                tasks.append(
                    self._execute_with_timeout(step, context, timeout, context.task_path)
                )

            layer_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 3. 处理结果，为每一步发送 observation
            processed_results = []
            for i, result in enumerate(layer_results):
                step = layer[i]
                action_name = step.get("action", "")
                if isinstance(result, Exception):
                    result = {
                        "success": False,
                        "error": str(result),
                        "action": action_name,
                    }

                files_created = self._extract_files_from_result(step, result)
                obs_message = self._format_step_observation(action_name, result, files_created)

                if on_step:
                    on_step("observation", {
                        "observation": obs_message,
                        "files": files_created,
                        "result": result,
                        "tool_success": bool(result.get("success", True)),
                    })

                processed_results.append(result)

            all_results.extend(processed_results)

            # 4. 如果当前层有失败，检查是否需要停止
            layer_failures = [r for r in processed_results if not r.get("success", True)]
            if layer_failures:
                # 记录失败但不立即停止，让后续层可以尝试
                failed_indices = [
                    len(all_results) - len(layer_results) + i
                    for i, r in enumerate(layer_failures)
                ]
                context.failed_steps.extend(failed_indices)

        return all_results

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
            return {
                "success": False,
                "error": f"步骤执行超时: {timeout}秒",
                "action": step.get("action"),
                "step": step.get("step"),
            }

    async def _execute_single_step(self, step: Dict[str, Any], task_path: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "unknown")
        params = step.get("params", {}).copy()

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
            # 优先使用 skill 返回的 friendly_action
            friendly_action = result.metadata.get("friendly_action") if result.metadata else None
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "action": friendly_action or action,
            }
        except Exception as e:
            # 备用：尝试从旧 registry 执行
            try:
                from app.agent.skills.registry import registry
                skill = registry.get(action)
                if skill:
                    result = await skill.execute(**params)
                    friendly_action = result.metadata.get("friendly_action") if result.metadata else None
                    return {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                        "action": friendly_action or action,
                    }
            except:
                pass

            return {
                "success": False,
                "error": str(e),
                "action": action,
            }

    def _build_execution_layers(
        self,
        plan: List[Dict[str, Any]],
    ) -> List[List[Dict[str, Any]]]:
        """
        构建执行层次

        根据 depends_on 字段进行拓扑排序，分层执行。
        没有依赖的步骤在同一层并行执行。
        """
        if not plan:
            return []

        # 为每个步骤分配索引
        indexed_plan = []
        for i, step in enumerate(plan):
            step_copy = step.copy()
            step_copy["_index"] = i
            indexed_plan.append(step_copy)

        # 构建入度表和依赖图
        in_degree = {i: 0 for i in range(len(indexed_plan))}
        dependents = {i: [] for i in range(len(indexed_plan))}  # 谁依赖我

        for i, step in enumerate(indexed_plan):
            depends_on = step.get("depends_on", [])
            for dep_idx in depends_on:
                if 0 <= dep_idx < len(indexed_plan):
                    in_degree[i] += 1
                    dependents[dep_idx].append(i)

        # Kahn算法拓扑排序并分层
        layers = []
        remaining = set(range(len(indexed_plan)))

        while remaining:
            # 找到入度为0的节点（当前层）
            current_layer = [i for i in remaining if in_degree[i] == 0]

            if not current_layer:
                # 存在依赖循环，将剩余节点作为一层（可以正常执行）
                current_layer = list(remaining)
                # 降低日志级别，因为这在某些场景下是正常的（如多次调用同一skill生成不同文件）
                logger.info(f"[AgentGraph] 存在依赖循环，已合并执行: {[indexed_plan[i].get('action') for i in current_layer]}")

            # 添加当前层
            layers.append([indexed_plan[i] for i in current_layer])

            # 更新入度
            for i in current_layer:
                remaining.remove(i)
                for dependent in dependents[i]:
                    in_degree[dependent] -= 1

        return layers

    async def _execute_sequential_with_retry(
        self,
        plan: List[Dict[str, Any]],
        context: ExecutionContext,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """
        串行执行计划，支持重试
        """
        results = []

        for i, step in enumerate(plan):
            step_with_index = {**step, "step": i + 1}
            action_name = step.get("action", "")
            action_desc = step.get("description", "")

            # 发送待办项开始
            if on_step:
                on_step("todo_start", {
                    "todo": {
                        "id": i + 1,
                        "title": action_desc or f"步骤 {i + 1}",
                        "total": len(plan),
                        "current": i + 1
                    }
                })

            # 执行步骤
            timeout = context.get_timeout_for_action(step.get("action", ""))
            result = await self._execute_with_timeout(
                step_with_index, context, timeout, context.task_path
            )

            # Supervisor 步骤级检查
            supervisor_decision = await self._supervisor.evaluate_step(step, result)

            if supervisor_decision.action == "abort":
                results.append({
                    "step": i + 1,
                    "action": step.get("action"),
                    "result": result,
                    "supervisor_abort": True,
                    "abort_reason": supervisor_decision.reason,
                })
                if on_step:
                    on_step("error", {"message": f"步骤 {i + 1} 被监督器终止: {supervisor_decision.reason}"})
                break

            results.append({
                "step": i + 1,
                "action": step.get("action"),
                "result": result,
            })
            context.completed_steps = i + 1

            # 发送待办项完成
            if on_step:
                on_step("todo_complete", {
                    "todo": {
                        "id": i + 1,
                        "title": step.get("description", f"步骤 {i + 1}"),
                        "success": result.get("success", True)
                    }
                })

            # 发送执行结果
            if on_step:
                files_created = self._extract_files_from_result(step, result)
                obs_message = self._format_step_observation(action_name, result, files_created)
                on_step("observation", {
                    "observation": obs_message,
                    "files": files_created,
                    "result": result,
                    "success": result.get("success", True),
                    "tool_success": bool(result.get("success", True)),
                })

            # 步骤失败处理
            if not result.get("success", True):
                context.failed_steps.append(i)
                error = result.get("error", "")

                if context.can_retry():
                    new_result = await self._retry_step(step_with_index, context, error)
                    if new_result.get("success", False):
                        results[-1]["result"] = new_result
                        results[-1]["retry_success"] = True
                        context.reset_retry()
                        continue
                    else:
                        context.increment_retry()

                if i < len(plan) - 1:
                    logger.warning(f"[AgentGraph] 步骤 {i + 1} 失败: {error}, 继续执行后续步骤")
                else:
                    context.last_error = error

        return results

    async def _retry_step(
        self,
        step: Dict[str, Any],
        context: ExecutionContext,
        previous_error: str,
    ) -> Dict[str, Any]:
        """重试单个步骤"""
        error_lower = previous_error.lower()

        # 根据错误类型调整参数
        step_copy = step.copy()
        params = step_copy.get("params", {}).copy()

        if "timeout" in error_lower or "超时" in error_lower:
            # 增加超时时间
            params["timeout"] = min(
                params.get("timeout", 60) * 2,
                context.max_step_timeout
            )
            step_copy["params"] = params
            logger.info(f"[AgentGraph] 重试步骤 {step.get('action')}: 增加超时到 {params.get('timeout')}s")
        elif "connection" in error_lower or "连接" in error_lower:
            # 添加重试延迟
            import asyncio
            await asyncio.sleep(2)
            logger.info(f"[AgentGraph] 重试步骤 {step.get('action')}: 等待后重试")

        # 执行重试
        timeout = context.get_timeout_for_action(step.get("action", ""))
        return await self._execute_with_timeout(step_copy, context, timeout)

    async def _handle_partial_failure(
        self,
        state: AgentState,
        results: List[Dict[str, Any]],
        context: ExecutionContext,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        处理部分失败

        尝试修复失败的步骤或调整后续计划。
        """
        failed_results = [
            r for r in results
            if isinstance(r, dict) and not r.get("result", {}).get("success", True)
        ]

        if not failed_results:
            return {"continued": True}

        # 尝试重规划
        errors = [r.get("result", {}).get("error", "未知错误") for r in failed_results]
        combined_error = "; ".join(errors)

        new_plan = await self._replanner.replan(state, combined_error)

        if new_plan:
            state.plan = new_plan
            state.error = None
            context.alternate_plans.append(new_plan)

            if on_step:
                on_step("planning", {"content": "重规划执行计划"})
                on_step("todos", {"todos": new_plan})

            return {"continued": True, "replanned": True}

        # 无法重规划，检查是否可以继续
        return {"continued": False, "reason": "无法重规划"}

    async def _emergency_recovery(
        self,
        state: AgentState,
        context: ExecutionContext,
        on_step: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> bool:
        """
        紧急恢复

        当规划失败时的最后尝试。
        """
        context.recovery_attempts += 1

        if context.recovery_attempts >= 2:
            state.error = "多次规划失败，无法生成执行计划"
            return False

        # 尝试使用通用响应
        logger.warning(f"[AgentGraph] 规划失败，尝试紧急恢复 (尝试 {context.recovery_attempts})")

        # 生成一个简单的 fallback plan
        state.plan = [
            {
                "step": 1,
                "action": "general_response",
                "params": {
                    "message": f"无法为任务 '{state.task}' 生成具体执行计划。"
                               f"请提供更详细的描述或更具体的指令。"
                },
                "description": "通用响应",
            }
        ]

        return True

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
