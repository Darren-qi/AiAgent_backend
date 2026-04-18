"""Agent 主图 - LangGraph 核心编排 (统一执行模式)"""

import logging
import json
import re
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

            if on_step:
                final_message = None
                for msg in reversed(state.messages):
                    if msg.get("type") == "final":
                        final_message = msg.get("content")
                        break
                on_step("complete", {
                    "result": final_message or (
                        state.results[-1].get("result", {}).get("data")
                        if state.results else None
                    )
                })

            # 任务完成，清除持久化状态
            if self._state_manager and session_id:
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

        for i in range(start_index, len(todos)):
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
                "success": todo_result.get("success", False)
            })

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
        failed_count = sum(1 for r in all_results if not r.get("success", False))
        if failed_count > 0:
            logger.warning(f"[AgentGraph] {failed_count}/{len(all_results)} 个待办失败")

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

        # 检查终止
        should_stop, stop_reason = self._check_termination()
        if should_stop:
            return {"success": False, "summary": stop_reason, "cancelled": True}

        # 检查中断
        if self._check_cancelled():
            return {"success": False, "summary": "用户取消执行", "cancelled": True}

        max_loop_iterations = 5
        last_error = None
        last_execution_result = None

        for loop_idx in range(max_loop_iterations):
            # 检查终止
            should_stop, stop_reason = self._check_termination()
            if should_stop:
                return {"success": False, "summary": stop_reason, "cancelled": True}

            logger.debug(f"[AgentGraph] 待办 {todo_id} 循环 {loop_idx + 1}/{max_loop_iterations}")

            # === Thought 阶段 ===
            thought_context = context
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

            # === Planning 阶段 ===
            plan_result = await self._planner.plan_action_with_feedback(
                task=state.task,
                todo=todo_item.to_dict() if hasattr(todo_item, "to_dict") else todo,
                thought=thought,
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

            planning_content = f"动作: {action}\n原因: {reason}"
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
            observation_result = await self._planner.observe(
                state.task, todo_item.to_dict() if hasattr(todo_item, "to_dict") else todo,
                action, merged_params, execution_result
            )

            # 检查取消（LLM 调用后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            obs_content = f"完成状态: {'已完成' if observation_result.get('completed', False) else '未完成'}\n"
            obs_content += f"原因: {observation_result.get('reason', '')}\n"
            obs_content += f"建议: {observation_result.get('suggestion', '')}"

            if on_step:
                on_step("observation", {
                    "content": obs_content,
                    "success": observation_result.get("success", False),
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
                if not execution_result.get("success", False):
                    self._state_manager.errors.append({
                        "todo_id": str(todo_id),
                        "error": last_error or "执行失败",
                    })
                todo_item.status = TodoStatus.COMPLETED if execution_result.get("success", False) else TodoStatus.FAILED
                todo_item.result = last_execution_result if execution_result.get("success", False) else ""
                todo_item.error = last_error if not execution_result.get("success", False) else ""

            # 每个 action 后保存状态（断点恢复）
            if self._state_manager:
                await self._state_manager.save_state()

            # 检查取消（状态保存后）
            if self._check_cancelled():
                return {"success": False, "summary": "用户取消执行", "cancelled": True}

            # 每个 action 后保存状态（断点恢复）
            if self._state_manager:
                await self._state_manager.save_state()

            # 如果 file_operations 成功，更新 context_obj.task_path（供后续待办使用）
            if execution_result.get("success", False) and action == "file_operations":
                result_data = execution_result.get("data", {})
                returned_project = result_data.get("project_name") if isinstance(result_data, dict) else None
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
                        try:
                            from app.agent.tools.storage.manager import StorageManager
                            storage = StorageManager()
                            file_tree = await storage.build_file_tree(returned_project)
                            files = result_data.get("files", []) if isinstance(result_data, dict) else []
                            on_step("project_tree", {
                                "project_name": returned_project,
                                "task_path": returned_project,
                                "files": files,
                                "file_tree": file_tree,
                            })
                        except Exception as e:
                            logger.warning(f"[AgentGraph] 构建文件树失败: {e}")
                            files = result_data.get("files", []) if isinstance(result_data, dict) else []
                            on_step("project_tree", {
                                "project_name": returned_project,
                                "task_path": returned_project,
                                "files": files,
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

            # 执行成功但观察判断未完成，强制完成
            if execution_result.get("success", False) and not observation_result.get("completed", False):
                logger.info(f"[AgentGraph] 待办 {todo_id} 执行成功但观察判断未完成，强制标记为完成")
                return {
                    "success": True,
                    "summary": "执行成功",
                    "iteration": loop_idx + 1,
                    "action": action,
                    "project_name": (
                        context_obj.task_path
                        if action == "file_operations"
                        else None
                    )
                }

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
        """确保 params 中有 task_path"""
        if "task_path" in params and params["task_path"]:
            return params

        task_path_actions = {"file_operations", "add_files_to_project", "improve_file"}
        if action not in task_path_actions:
            return params

        task_path = await self._get_session_task_path()
        if task_path:
            params = params.copy()
            params["task_path"] = task_path
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
                    on_step("observation", {"observation": obs_message, "files": files_created, "result": result})

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
                    "success": result.get("success", True)
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
            "result": final_message or (
                state.results[-1].get("result", {}).get("data")
                if state.results else None
            ),
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
