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
        state = AgentState(
            messages=[],
            task=task,
            context=context or {},
        )

        if session_id:
            state.context["session_id"] = session_id
        if task_id:
            state.context["task_id"] = task_id

        logger.info(f"[AgentGraph] 开始执行任务: {task[:100]}...")

        # 执行过程中调用回调
        if on_step:
            on_step("planning", {"status": "开始执行任务"})

        try:
            # 1. 安全检查
            state = await self._safety_check(state)
            if state.error:
                if on_step:
                    on_step("error", {"message": state.error})
                return self._format_error(state.error, state)

            # 2. 意图检测
            state = await self._detect_intent(state)
            logger.info(f"[AgentGraph] 意图检测结果: {state.intent}, 置信度: {state.confidence}")

            # 3. 创建统一执行上下文 (替代复杂度评估 + 路由决策)
            exec_context = self._create_execution_context(state)
            if on_step:
                on_step("planning", {
                    "content": f"执行配置: 并行={exec_context.parallel_enabled}, "
                               f"最大迭代={exec_context.max_iterations}, "
                               f"超时={exec_context.default_step_timeout}s"
                })

            # 4. 统一执行引擎
            state = await self._execute_unified(state, exec_context, on_step)

            # 5. Supervisor 最终检查
            supervisor_decision = await self._supervisor.evaluate(state.to_dict())
            if supervisor_decision.action == "reject":
                state.error = supervisor_decision.reason
                if on_step:
                    on_step("error", {"message": state.error})
                return self._format_error(state.error, state)

            # 6. 结果整合
            state = await self._integrate_results(state)
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

            return self._format_response(state, exec_context)

        except Exception as e:
            logger.exception(f"[AgentGraph] 执行异常: {e}")
            state.error = str(e)
            if on_step:
                on_step("error", {"message": str(e)})
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
        统一执行引擎 - 所有任务共享同一套执行逻辑

        特性:
        - 迭代循环: 支持自动重规划
        - 并行执行: 独立步骤并行执行
        - Supervisor检查: 每步后自动评估
        - 死循环检测: 防止无限循环
        - 目标导向: 失败重试而非抛异常
        """
        context.status = ExecutionStatus.RUNNING

        for iteration in range(context.max_iterations):
            context.iteration = iteration

            # 迭代警告
            if context.should_warn_iteration():
                warning_msg = f"迭代次数已达 {iteration + 1}，接近上限 {context.max_iterations}"
                logger.warning(f"[AgentGraph] {warning_msg}")
                if on_step:
                    on_step("warning", {"message": warning_msg})

            # 1. 规划阶段
            state = await self._plan(state)
            if not state.plan:
                # 尝试紧急恢复
                if not await self._emergency_recovery(state, context, on_step):
                    break
                continue

            # 记录计划到历史
            context.record_plan(state.plan.copy())

            # 1.5 计划分析阶段 - 对每个计划项进行深入分析
            plan_analysis = await self._planner.analyze_plan(state.task, state.plan)
            if on_step and plan_analysis:
                on_step("thinking", {"content": plan_analysis})

            if on_step:
                on_step("todos", {"todos": state.plan})

            # 2. 执行计划 (并行或串行)
            if context.parallel_enabled and len(state.plan) > 1:
                results = await self._execute_parallel_with_deps(state.plan, context, on_step)
            else:
                results = await self._execute_sequential_with_retry(state.plan, context, on_step)

            state.results = results
            context.record_result({"results": results, "iteration": iteration})

            # 3. Observation 阶段 - 死循环检测 + Supervisor评估
            observation = await self._observe_execution(iteration, state, results, context)

            # 4. 根据观察结果决策
            if observation.loop_status != LoopDetectionResult.NORMAL:
                # 检测到异常模式
                if observation.should_terminate:
                    state.error = observation.termination_reason
                    context.termination_reason = observation.termination_reason
                    if on_step:
                        on_step("warning", {
                            "message": f"执行终止: {observation.termination_reason}",
                            "fallback": observation.fallback_action
                        })
                    break

            # 5. 检查执行结果
            all_success = self._all_steps_succeeded(results)
            any_failure = any(not r.get("success", True) for r in results if isinstance(r, dict))

            if all_success:
                # 所有步骤成功，任务完成
                break

            if any_failure:
                # 部分失败，尝试修复
                handle_result = await self._handle_partial_failure(state, results, context, on_step)
                if not handle_result.get("continued"):
                    break

            # 6. 检查任务是否完成
            if self._is_task_complete(state):
                break

        context.status = ExecutionStatus.SUCCEEDED if not state.error else ExecutionStatus.FAILED

        # 记录执行统计
        state.context["execution_stats"] = context.to_dict()

        return state

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
                self._execute_single_step(step, task_path),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"步骤执行超时: {timeout}秒",
                "action": step.get("action"),
                "step": step.get("step"),
            }

    async def _execute_single_step(self, step: Dict[str, Any], task_path: Optional[str] = None) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "unknown")
        params = step.get("params", {}).copy()

        # 传递 task_path 到 skill，让它能正确写入 AiAgent/tasks/
        if task_path:
            params["task_path"] = task_path

        try:
            from app.agent.skills.registry import registry
            skill = registry.get(action)

            if skill:
                result = await skill.execute(**params)
                return {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "action": action,
                }
            else:
                return {
                    "success": False,
                    "error": f"未找到 Skill: {action}",
                    "action": action,
                }
        except Exception as e:
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

        每个步骤失败后，根据错误类型决定是否重试。
        """
        results = []

        for i, step in enumerate(plan):
            step_with_index = {**step, "step": i + 1}
            action_name = step.get("action", "")
            action_desc = step.get("description", "")

            # 执行步骤前，先输出思考分析
            if on_step:
                step_analysis = self._generate_step_analysis(step, i + 1, len(plan))
                on_step("thinking", {"content": step_analysis})

            if on_step:
                on_step("todo_start", {
                    "todo": {"id": i + 1, "title": action_desc or f"步骤 {i + 1}"}
                })
                on_step("action", {
                    "action": action_name,
                    "input": step,
                    "description": action_desc,
                    "step_index": i + 1,
                    "total_steps": len(plan)
                })

            # 获取超时时间
            timeout = context.get_timeout_for_action(step.get("action", ""))

            # 执行步骤
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
                # 遇到 abort 停止执行
                if on_step:
                    on_step("error", {"message": f"步骤 {i + 1} 被监督器终止: {supervisor_decision.reason}"})
                break

            results.append({
                "step": i + 1,
                "action": step.get("action"),
                "result": result,
            })
            context.completed_steps = i + 1

            # 提取生成的文件路径
            files_created = self._extract_files_from_result(step, result)

            # 生成人类可读的观察消息
            obs_message = self._format_step_observation(action_name, result, files_created)

            if on_step:
                on_step("observation", {"observation": obs_message, "files": files_created, "result": result})
                on_step("todo_complete", {
                    "todo": {"id": i + 1, "title": step.get("description", f"步骤 {i + 1}")}
                })

            # 步骤失败处理
            if not result.get("success", True):
                context.failed_steps.append(i)
                error = result.get("error", "")

                # 尝试重试
                if context.can_retry():
                    # 根据错误类型尝试重试
                    new_result = await self._retry_step(step_with_index, context, error)
                    if new_result.get("success", False):
                        results[-1]["result"] = new_result
                        results[-1]["retry_success"] = True
                        context.reset_retry()
                        continue
                    else:
                        context.increment_retry()

                # 重试失败或不可重试，记录错误
                if i < len(plan) - 1:
                    # 可以继续执行后续步骤（不致命）
                    logger.warning(f"[AgentGraph] 步骤 {i + 1} 失败: {error}, 继续执行后续步骤")
                else:
                    # 最后一步失败，任务失败
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
            state.messages.append({
                "type": "final",
                "content": integrated,
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
