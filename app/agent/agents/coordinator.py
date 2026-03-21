"""多智能体协调器"""

import logging
from typing import Dict, Any, Optional, List

from app.agent.agents.planner_agent import PlannerAgent
from app.agent.agents.executor_agent import ExecutorAgent
from app.agent.agents.critic_agent import CriticAgent
from app.agent.agents.supervisor_agent import SupervisorAgent
from app.agent.agents.base import AgentResult

logger = logging.getLogger(__name__)


class MultiAgentCoordinator:
    """
    多智能体协调器

    负责协调多个 Agent 的协作执行：
    - PlannerAgent: 任务规划
    - ExecutorAgent: 任务执行
    - CriticAgent: 结果审查
    - SupervisorAgent: 全程监督
    """

    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.critic = CriticAgent()
        self.supervisor = SupervisorAgent()

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        执行多智能体协作

        工作流程：
        1. Supervisor 评估是否需要多 Agent 协作
        2. Planner 生成任务计划
        3. Executor 执行子任务
        4. Critic 评估结果
        5. 如需要，循环重规划
        6. Supervisor 最终确认

        Args:
            task: 用户任务
            context: 执行上下文

        Returns:
            AgentResult
        """
        logger.info(f"[MultiAgentCoordinator] 开始执行多智能体任务: {task[:80]}...")
        context = context or {}
        iteration = 0
        max_iterations = context.get("max_iterations", 5)

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[MultiAgentCoordinator] ===== 第 {iteration} 轮迭代 =====")

            # Step 1: Supervisor 评估
            supervisor_result = await self.supervisor.run(
                task=task,
                current_state={"results": [], "iteration": iteration},
                context=context
            )
            supervisor_decision = supervisor_result.data

            if supervisor_decision.get("action") == "abort":
                logger.warning(f"[MultiAgentCoordinator] Supervisor 终止任务: {supervisor_decision.get('reason')}")
                return AgentResult(
                    success=False,
                    error=supervisor_decision.get("reason"),
                    metadata={"iteration": iteration}
                )

            # Step 2: Planner 生成计划
            logger.info("[MultiAgentCoordinator] Planner 生成任务计划...")
            planner_result = await self.planner.run(task, context)
            if not planner_result.success:
                return AgentResult(
                    success=False,
                    error=f"规划失败: {planner_result.error}",
                    metadata={"iteration": iteration}
                )

            plan = planner_result.data
            subtasks = plan.get("subtasks", [])
            logger.info(f"[MultiAgentCoordinator] 生成 {len(subtasks)} 个子任务")

            # Step 3: Executor 执行
            logger.info("[MultiAgentCoordinator] Executor 执行子任务...")
            execution_mode = "parallel" if self._should_parallel(subtasks) else "sequential"
            executor_result = await self.executor.run(subtasks, mode=execution_mode, context=context)

            if not executor_result.success:
                logger.warning(f"[MultiAgentCoordinator] 执行失败: {executor_result.error}")

            # Step 4: Critic 审查
            logger.info("[MultiAgentCoordinator] Critic 审查结果...")
            results = executor_result.data.get("results", []) if executor_result.success else []
            critic_result = await self.critic.run(task, results, context)

            if not critic_result.success:
                logger.warning(f"[MultiAgentCoordinator] 审查失败: {critic_result.error}")

            # Step 5: 检查是否需要继续
            needs_replan = critic_result.data.get("needs_replan", False) if critic_result.success else True

            if not needs_replan:
                logger.info("[MultiAgentCoordinator] 任务完成，审查通过")
                return AgentResult(
                    success=True,
                    data={
                        "task": task,
                        "plan": plan,
                        "results": results,
                        "evaluation": critic_result.data if critic_result.success else None
                    },
                    metadata={
                        "iteration": iteration,
                        "subtasks_completed": len(results),
                        "mode": execution_mode
                    }
                )

            # Step 6: 需要重规划，继续循环
            logger.info("[MultiAgentCoordinator] 审查建议重规划，继续迭代...")

        # 达到最大迭代次数
        logger.warning(f"[MultiAgentCoordinator] 达到最大迭代次数 ({max_iterations})，强制结束")
        return AgentResult(
            success=False,
            error=f"达到最大迭代次数 ({max_iterations})，任务未能完成",
            metadata={"iteration": iteration, "final_results": executor_result.data if executor_result.success else None}
        )

    def _should_parallel(self, subtasks: List[Dict[str, Any]]) -> bool:
        """判断是否应该并行执行"""
        if len(subtasks) < 2:
            return False

        # 检查是否有无依赖的独立任务
        independent_count = sum(1 for t in subtasks if not t.get("depends_on"))
        return independent_count >= 2

    async def execute_single(
        self,
        agent_type: str,
        input_data: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """单独执行某个 Agent"""
        agent_map = {
            "planner": self.planner,
            "executor": self.executor,
            "critic": self.critic,
            "supervisor": self.supervisor,
        }

        agent = agent_map.get(agent_type)
        if not agent:
            return AgentResult(success=False, error=f"未知的 Agent 类型: {agent_type}")

        return await agent.run(input_data, context)
