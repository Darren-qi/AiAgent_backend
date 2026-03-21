"""重规划节点"""

from typing import TYPE_CHECKING, Dict, Any, List

if TYPE_CHECKING:
    from app.agent.graphs.main_graph import AgentState


class Replanner:
    """重规划器"""

    def __init__(self):
        self.max_retries = 3

    async def replan(self, state: "AgentState", error: str) -> List[Dict[str, Any]]:
        """
        当任务失败时，重新规划执行路径

        分析错误原因，生成替代方案。
        """
        original_plan = state.plan or []
        current_step = state.current_step

        retry_count = state.context.get("retry_count", 0)

        if retry_count >= self.max_retries:
            return []

        new_plan = self._generate_alternative_plan(state, error)

        state.context["retry_count"] = retry_count + 1
        state.context["original_error"] = error

        return new_plan

    def _generate_alternative_plan(
        self, state: "AgentState", error: str
    ) -> List[Dict[str, Any]]:
        """
        生成替代计划

        根据错误类型选择不同的重试策略。
        """
        error_lower = error.lower()
        original_plan = state.plan or []

        if "timeout" in error_lower or "超时" in error_lower:
            return self._handle_timeout_alternative(original_plan)
        elif "network" in error_lower or "网络" in error_lower:
            return self._handle_network_alternative(original_plan)
        elif "permission" in error_lower or "权限" in error_lower:
            return self._handle_permission_alternative(original_plan)
        else:
            return self._handle_generic_alternative(original_plan)

    def _handle_timeout_alternative(
        self, original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        new_plan = []
        for step in original_plan:
            new_step = step.copy()
            new_step["params"] = {**step.get("params", {}), "timeout": 60}
            new_plan.append(new_step)
        return new_plan

    def _handle_network_alternative(
        self, original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return original_plan

    def _handle_permission_alternative(
        self, original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return []

    def _handle_generic_alternative(
        self, original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return original_plan
