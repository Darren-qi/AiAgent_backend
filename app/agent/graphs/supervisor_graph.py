"""监督图"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SupervisorDecision:
    """监督决策"""
    action: str
    reason: str
    next_step: Optional[int] = None


class SupervisorGraph:
    """
    监督图

    负责监督整个 Agent 的执行流程，做出高层决策：
    - 是否需要重规划
    - 是否需要人类确认
    - 是否需要降级处理
    """

    def __init__(self):
        self.confirmation_threshold = 0.7

    async def evaluate(
        self,
        state: Dict[str, Any]
    ) -> SupervisorDecision:
        """
        评估当前状态，做出决策

        Args:
            state: 当前 Agent 状态

        Returns:
            监督决策
        """
        error = state.get("error")
        success = state.get("success", True)
        retry_count = state.get("context", {}).get("retry_count", 0)
        budget_status = state.get("budget_status", "normal")

        if not success and retry_count >= 3:
            return SupervisorDecision(
                action="abort",
                reason="重试次数过多，终止任务",
                next_step=None
            )

        if not success and error:
            return SupervisorDecision(
                action="replan",
                reason=f"任务失败，需要重新规划: {error}",
                next_step=None
            )

        if budget_status == "degraded":
            return SupervisorDecision(
                action="degrade",
                reason="预算接近阈值，启用降级策略",
                next_step=None
            )

        if budget_status == "exhausted":
            return SupervisorDecision(
                action="reject",
                reason="预算已耗尽，拒绝新请求",
                next_step=None
            )

        return SupervisorDecision(
            action="continue",
            reason="任务执行正常",
            next_step=None
        )

    async def should_human_confirm(
        self,
        task: str,
        planned_actions: List[str]
    ) -> bool:
        """
        判断是否需要人工确认

        某些高风险操作需要人工确认才能执行。
        """
        high_risk_actions = {"delete", "drop", "shutdown", "reboot", "send_email"}
        high_risk_keywords = {"删除", "销毁", "关机", "重启", "大量发送"}

        for action in planned_actions:
            if action.lower() in high_risk_actions:
                return True

        task_lower = task.lower()
        for keyword in high_risk_keywords:
            if keyword in task_lower:
                return True

        return False

    async def suggest_model_downgrade(
        self,
        current_model: str,
        budget_percentage: float
    ) -> Optional[str]:
        """
        建议模型降级

        当预算紧张时，建议切换到更便宜的模型。
        """
        if budget_percentage < 90:
            return None

        downgrade_map = {
            "gpt-4-turbo": "gpt-3.5-turbo",
            "claude-3-opus": "claude-3-sonnet",
            "deepseek-chat": "deepseek-coder",
        }

        return downgrade_map.get(current_model)

    async def generate_recovery_plan(
        self,
        failed_step: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        生成恢复计划

        当某个步骤失败时，生成替代方案。
        """
        failed_action = failed_step.get("action", "")
        error = failed_step.get("error", "")

        alternative_map = {
            "http_client": [
                {"action": "retry", "params": {"delay": 5}},
                {"action": "http_client", "params": {"timeout": 60}},
            ],
            "crawler": [
                {"action": "http_client", "params": {}},
                {"action": "skip", "params": {}},
            ],
        }

        alternatives = alternative_map.get(failed_action, [
            {"action": "retry", "params": {}},
        ])

        return alternatives

    async def evaluate_step(
        self,
        step: Dict[str, Any],
        step_result: Dict[str, Any]
    ) -> SupervisorDecision:
        """
        评估单个步骤的执行结果

        Args:
            step: 当前步骤信息
            step_result: 步骤执行结果

        Returns:
            监督决策
        """
        success = step_result.get("success", True)
        error = step_result.get("error")

        # 步骤执行失败
        if not success:
            return SupervisorDecision(
                action="abort",
                reason=f"步骤 '{step.get('action')}' 执行失败: {error}",
                next_step=None
            )

        # 检查结果数据是否为空或异常
        data = step_result.get("data")
        if data is None and step.get("action") not in ["general_response", "notification"]:
            # 对于数据获取类步骤，空结果可能是问题
            logger.warning(f"[Supervisor] 步骤 {step.get('step')} 返回空数据")

        return SupervisorDecision(
            action="continue",
            reason=f"步骤 '{step.get('action')}' 执行成功",
            next_step=None
        )
