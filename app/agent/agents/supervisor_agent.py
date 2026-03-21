"""监督 Agent"""

import logging
from typing import Dict, Any, Optional

from app.agent.agents.base import BaseAgent, AgentType, AgentResult

logger = logging.getLogger(__name__)


class SupervisorAgent(BaseAgent):
    """监督 Agent - 负责任务执行的全程监督和控制"""

    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.SUPERVISOR, name="SupervisorAgent", **kwargs)
        self.max_iterations = 5
        self.budget_warning_threshold = 0.8
        self.budget_critical_threshold = 0.95

    def _get_default_system_prompt(self) -> str:
        return """你是一个任务监督专家。你的职责是监督任务执行的全过程，确保任务高效、准确地完成。

监督职责：
1. 监控任务执行进度和状态
2. 评估预算使用情况
3. 决定是否继续、重试或终止任务
4. 识别执行异常并触发相应处理流程

决策类型：
- continue: 继续执行当前任务
- retry: 重试当前步骤
- replan: 重新规划任务
- abort: 终止任务执行
- done: 任务完成"""

    async def run(
        self,
        task: str,
        current_state: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """执行监督任务"""
        logger.info(f"[SupervisorAgent] 监督任务: {task[:50]}...")
        context = context or {}

        # 检查各种条件
        iteration = context.get("iteration", 0)
        budget_status = context.get("budget_status", "normal")
        error = current_state.get("error")
        results = current_state.get("results", [])

        # 决策逻辑
        decision = self._make_decision(
            iteration=iteration,
            budget_status=budget_status,
            error=error,
            results_count=len(results),
            context=context
        )

        logger.info(f"[SupervisorAgent] 决策: {decision['action']} - {decision['reason']}")

        return AgentResult(
            success=True,
            data=decision,
            metadata={
                "iteration": iteration,
                "budget_status": budget_status,
                "results_count": len(results)
            }
        )

    def _make_decision(
        self,
        iteration: int,
        budget_status: str,
        error: Optional[str],
        results_count: int,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """做出监督决策"""
        # 1. 检查预算状态
        if budget_status == "exhausted":
            return {
                "action": "abort",
                "reason": "预算已耗尽，无法继续执行"
            }

        if budget_status == "degraded":
            return {
                "action": "continue",
                "reason": "预算接近阈值，启用低资源模式继续执行"
            }

        # 2. 检查错误
        if error:
            if iteration >= self.max_iterations - 1:
                return {
                    "action": "abort",
                    "reason": f"已达到最大重试次数 ({self.max_iterations})，任务终止"
                }
            return {
                "action": "replan",
                "reason": f"执行出错，需要重新规划: {error}"
            }

        # 3. 检查迭代次数
        if iteration >= self.max_iterations:
            return {
                "action": "done",
                "reason": f"已达到最大迭代次数 ({self.max_iterations})，强制结束"
            }

        # 4. 检查结果
        if results_count == 0:
            return {
                "action": "continue",
                "reason": "任务刚开始执行，继续"
            }

        # 5. 检查是否完成（假设有一定数量的成功结果即算完成）
        if results_count >= 1:
            return {
                "action": "done",
                "reason": "任务执行完成"
            }

        return {
            "action": "continue",
            "reason": "任务执行中，继续监控"
        }
