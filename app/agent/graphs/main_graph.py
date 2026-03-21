"""Agent 主图 - LangGraph 核心编排"""

import logging
import json
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from app.agent.graphs.nodes.intent_detector import IntentDetector
from app.agent.graphs.nodes.planner import Planner
from app.agent.graphs.nodes.executor import Executor
from app.agent.graphs.nodes.integrator import Integrator
from app.agent.graphs.nodes.guard import Guard
from app.agent.graphs.dynamic_subgraph import DynamicSubgraph
from app.agent.graphs.supervisor_graph import SupervisorGraph, SupervisorDecision
from app.agent.graphs.nodes.replanner import Replanner

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """Agent 状态"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    task: str = ""
    intent: Optional[str] = None
    intents: List[str] = field(default_factory=list)
    plan: Optional[List[Dict[str, Any]]] = None
    current_step: int = 0
    results: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    routing: Optional[Dict[str, Any]] = None
    confidence: float = 0.0

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
    """Agent 主图 - 编排整个 Agent 执行流程"""

    def __init__(self):
        self._intent_detector = IntentDetector()
        self._planner = Planner()
        self._executor = Executor()
        self._integrator = Integrator()
        self._guard = Guard()
        self._dynamic_subgraph = DynamicSubgraph()
        self._supervisor = SupervisorGraph()
        self._replanner = Replanner()

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行任务的主入口

        Args:
            task: 用户任务描述
            context: 执行上下文（用户ID、会话ID等）
            session_id: 会话ID
            task_id: 任务ID

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

        try:
            # 1. 安全检查
            state = await self._safety_check(state)
            if state.error:
                return self._format_error(state.error, state)

            # 2. 意图检测
            state = await self._detect_intent(state)
            logger.info(f"[AgentGraph] 意图检测结果: {state.intent}, 置信度: {state.confidence}")

            # 3. 复杂度评估 + 路由决策
            state = await self._evaluate_complexity(state)

            # 4. 根据路由选择执行模式
            mode = state.routing.get("mode", "simple") if state.routing else "simple"
            logger.info(f"[AgentGraph] 路由决策: {mode}")

            if mode == "multi_agent":
                state = await self._execute_multi_agent(state)
            elif mode == "dynamic_subgraph":
                state = await self._execute_with_subgraph(state)
            else:
                state = await self._execute_simple(state)

            # 5. Supervisor 最终检查
            supervisor_decision = await self._supervisor.evaluate(state.to_dict())
            if supervisor_decision.action == "reject":
                state.error = supervisor_decision.reason
                return self._format_error(state.error, state)

            # 6. 结果整合
            state = await self._integrate_results(state)

            return self._format_response(state)

        except Exception as e:
            logger.exception(f"[AgentGraph] 执行异常: {e}")
            state.error = str(e)
            return self._format_error(state.error, state)

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

    async def _evaluate_complexity(self, state: AgentState) -> AgentState:
        """评估任务复杂度，决定路由"""
        complexity_result = await self._intent_detector.detect_complexity(
            state.task, state.intents
        )
        state.routing = complexity_result
        return state

    async def _execute_simple(self, state: AgentState) -> AgentState:
        """简单模式：意图检测 -> 规划 -> 执行"""
        # 任务规划
        state = await self._plan(state)
        if state.error or not state.plan:
            state.error = state.error or "规划失败：未能生成执行计划"
            return state

        # 执行计划
        state = await self._execute_plan(state)
        return state

    async def _execute_with_subgraph(self, state: AgentState) -> AgentState:
        """动态子图模式：支持并行执行"""
        # 任务规划
        state = await self._plan(state)
        if state.error or not state.plan:
            state.error = state.error or "规划失败"
            return state

        # 使用动态子图执行
        try:
            result = await self._dynamic_subgraph.execute(
                steps=state.plan,
                mode="parallel" if state.routing.get("routing", {}).get("parallel") else "sequential",
                context=state.context,
            )
            state.results = result.get("results", [])
            if result.get("error"):
                state.error = result["error"]
        except Exception as e:
            state.error = f"子图执行失败: {str(e)}"
            logger.exception(f"[AgentGraph] 子图执行异常")

        return state

    async def _execute_multi_agent(self, state: AgentState) -> AgentState:
        """多智能体模式：Planner + Executor + Critic 协作"""
        max_iterations = state.routing.get("routing", {}).get("max_iterations", 5) if state.routing else 5

        for iteration in range(max_iterations):
            # 1. Supervisor 检查
            decision = await self._supervisor.evaluate(state.to_dict())
            if decision.action == "abort":
                state.error = decision.reason
                break
            if decision.action == "reject":
                state.error = decision.reason
                break
            if decision.action == "done":
                break

            # 2. 任务规划
            state = await self._plan(state)
            if not state.plan:
                state.error = "多Agent规划失败"
                break

            # 3. 执行计划
            state = await self._execute_plan(state)

            # 4. 检查执行结果
            if state.error:
                # 尝试重规划
                new_plan = await self._replanner.replan(state, state.error)
                if new_plan:
                    state.plan = new_plan
                    state.error = None
                    continue
                break

            # 5. 评估是否需要继续
            if self._is_task_complete(state):
                break

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

    async def _execute_plan(self, state: AgentState) -> AgentState:
        """执行计划"""
        if not state.plan:
            state.error = "没有可执行的计划"
            return state

        results = []
        for i, step in enumerate(state.plan):
            step_result = await self._executor.execute_step(step)

            # Supervisor 步骤级检查
            supervisor_decision = await self._supervisor.evaluate_step(step, step_result)
            if supervisor_decision.action == "abort":
                state.error = f"步骤 {i+1} 被监督器终止: {supervisor_decision.reason}"
                state.results = results
                return state

            results.append({
                "step": i + 1,
                "action": step.get("action"),
                "result": step_result,
            })
            state.current_step = i + 1

            if not step_result.get("success", True):
                state.error = f"步骤 {i+1} 执行失败: {step_result.get('error')}"
                state.results = results
                break

        state.results = results
        return state

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
                    "routing": state.routing.get("mode") if state.routing else "simple",
                }
            })
        except Exception as e:
            state.error = f"结果整合失败: {str(e)}"
            logger.exception(f"[AgentGraph] 整合结果异常")
        return state

    def _is_task_complete(self, state: AgentState) -> bool:
        """判断任务是否完成"""
        if state.error:
            return True
        if not state.results:
            return False
        # 检查所有步骤是否都成功
        return all(
            r.get("result", {}).get("success", False)
            for r in state.results
        )

    def _format_response(self, state: AgentState) -> Dict[str, Any]:
        """格式化响应"""
        final_message = None
        for msg in reversed(state.messages):
            if msg.get("type") == "final":
                final_message = msg.get("content")
                break

        return {
            "success": state.error is None,
            "result": final_message or (state.results[-1]["result"].get("data") if state.results else None),
            "error": state.error,
            "intent": state.intent,
            "intents": state.intents,
            "confidence": state.confidence,
            "plan": state.plan,
            "steps_executed": len(state.results) if state.results else 0,
            "routing_mode": state.routing.get("mode") if state.routing else "simple",
        }

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
            "routing_mode": state.routing.get("mode") if state.routing else "unknown",
        }
