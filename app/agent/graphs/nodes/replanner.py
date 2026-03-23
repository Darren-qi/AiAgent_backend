"""重规划节点 - 渐进式重规划策略"""

from typing import TYPE_CHECKING, Dict, Any, List, Optional

if TYPE_CHECKING:
    from app.agent.graphs.main_graph import AgentState

import logging

logger = logging.getLogger(__name__)


class Replanner:
    """
    重规划器 - 渐进式重规划策略

    改进:
    1. 渐进式重规划: 根据失败次数决定重规划策略
    2. 上下文保留: 保留已成功的步骤结果
    3. 智能替代: 根据错误类型选择替代方案
    """

    def __init__(self):
        self.max_retries = 3
        # 渐进式重规划策略配置
        self.skip_on_retry_2 = True      # 第2次重试时跳过失败步骤
        self.fallback_on_retry_3 = True  # 第3次重试时使用兜底方案

    async def replan(
        self,
        state: "AgentState",
        error: str,
        retry_count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        当任务失败时，重新规划执行路径

        分析错误原因，生成替代方案。
        采用渐进式策略:
        - 第1次: 仅调整失败步骤参数
        - 第2次: 跳过失败步骤，继续执行
        - 第3次: 使用兜底方案或返回部分结果
        """
        original_plan = state.plan or []
        current_step = state.current_step

        # 获取重试次数
        if retry_count is None:
            retry_count = state.context.get("retry_count", 0)

        if retry_count >= self.max_retries:
            logger.warning(f"[Replanner] 重试次数已达上限 ({self.max_retries})")
            return []

        logger.info(f"[Replanner] 开始重规划 (重试 {retry_count + 1}/{self.max_retries})")

        # 渐进式策略选择
        if retry_count == 0:
            # 第1次: 调整参数重试
            new_plan = self._retry_with_adjusted_params(original_plan, error, state)
        elif retry_count == 1 and self.skip_on_retry_2:
            # 第2次: 跳过失败步骤
            new_plan = self._skip_failed_steps(original_plan, error, state)
        elif retry_count >= 2 and self.fallback_on_retry_3:
            # 第3次+: 兜底方案
            new_plan = self._generate_fallback_plan(state, error)
        else:
            # 通用替代
            new_plan = self._generate_alternative_plan(state, error)

        # 更新上下文
        state.context["retry_count"] = retry_count + 1
        state.context["original_error"] = error
        state.context["replan_attempts"] = state.context.get("replan_attempts", 0) + 1

        return new_plan

    def _retry_with_adjusted_params(
        self,
        original_plan: List[Dict[str, Any]],
        error: str,
        state: "AgentState"
    ) -> List[Dict[str, Any]]:
        """
        第1次重试: 调整失败步骤的参数

        根据错误类型调整参数:
        - timeout → 增加超时时间
        - network → 添加重试延迟
        - 其他 → 保持原计划
        """
        error_lower = error.lower()
        new_plan = []

        for step in original_plan:
            step_copy = step.copy()
            params = step_copy.get("params", {}).copy()

            # 根据错误类型调整参数
            if "timeout" in error_lower or "超时" in error_lower:
                # 增加超时
                current_timeout = params.get("timeout", 60)
                params["timeout"] = min(current_timeout * 2, 600)
                logger.info(f"[Replanner] 调整超时: {current_timeout}s → {params['timeout']}s")

            elif "network" in error_lower or "网络" in error_lower or "connection" in error_lower:
                # 添加延迟参数
                params["retry_delay"] = params.get("retry_delay", 2)
                logger.info(f"[Replanner] 添加重试延迟: {params['retry_delay']}s")

            elif "rate limit" in error_lower or "限流" in error_lower:
                # 添加冷却时间
                params["cooldown"] = params.get("cooldown", 5)
                logger.info(f"[Replanner] 添加限流冷却: {params['cooldown']}s")

            step_copy["params"] = params
            new_plan.append(step_copy)

        return new_plan

    def _skip_failed_steps(
        self,
        original_plan: List[Dict[str, Any]],
        error: str,
        state: "AgentState"
    ) -> List[Dict[str, Any]]:
        """
        第2次重试: 跳过失败的步骤

        保留成功的步骤，将失败的步骤标记为 skip 或替换为简单操作。
        """
        new_plan = []
        failed_action = None

        # 找出失败的操作类型
        if state.results:
            for result in reversed(state.results):
                if isinstance(result, dict):
                    step_result = result.get("result", {})
                    if isinstance(step_result, dict) and not step_result.get("success", True):
                        failed_action = result.get("action")
                        break

        for step in original_plan:
            step_copy = step.copy()

            # 跳过失败的操作类型
            if step.get("action") == failed_action:
                logger.info(f"[Replanner] 跳过失败步骤: {failed_action}")
                step_copy["action"] = "general_response"
                step_copy["params"] = {
                    "message": f"无法执行 '{failed_action}' 操作 ({error})，已跳过"
                }
                step_copy["description"] = "跳过失败步骤"
                step_copy["skipped"] = True

            new_plan.append(step_copy)

        return new_plan

    def _generate_fallback_plan(
        self,
        state: "AgentState",
        error: str
    ) -> List[Dict[str, Any]]:
        """
        第3次+: 兜底方案

        返回一个最小化的计划，只执行最核心的操作。
        """
        logger.warning(f"[Replanner] 使用兜底方案")

        # 收集已成功的结果
        successful_results = []
        if state.results:
            for result in state.results:
                if isinstance(result, dict):
                    step_result = result.get("result", {})
                    if isinstance(step_result, dict) and step_result.get("success", False):
                        successful_results.append({
                            "action": result.get("action"),
                            "data": step_result.get("data"),
                        })

        # 生成兜底响应
        fallback_message = self._generate_fallback_message(state.task, error, successful_results)

        return [
            {
                "step": 1,
                "action": "general_response",
                "params": {
                    "message": fallback_message
                },
                "description": "任务执行结果",
                "is_fallback": True,
            }
        ]

    def _generate_fallback_message(
        self,
        task: str,
        error: str,
        successful_results: List[Dict]
    ) -> str:
        """生成兜底消息"""
        message_parts = []

        if successful_results:
            message_parts.append("已完成部分任务:")
            for result in successful_results:
                message_parts.append(f"- {result.get('action')}: 成功")

        message_parts.append(f"\n遇到问题: {error}")
        message_parts.append(f"\n任务: {task}")
        message_parts.append("\n建议: 请重试或提供更详细的信息")

        return "\n".join(message_parts)

    def _generate_alternative_plan(
        self,
        state: "AgentState",
        error: str
    ) -> List[Dict[str, Any]]:
        """
        通用替代计划生成

        根据错误类型选择不同的重试策略。
        """
        error_lower = error.lower()
        original_plan = state.plan or []

        if "timeout" in error_lower or "超时" in error_lower:
            return self._handle_timeout_alternative(original_plan)
        elif "network" in error_lower or "网络" in error_lower:
            return self._handle_network_alternative(original_plan)
        elif "permission" in error_lower or "权限" in error_lower:
            return self._handle_permission_alternative(original_plan, state)
        else:
            return self._handle_generic_alternative(original_plan, state)

    def _handle_timeout_alternative(
        self,
        original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """处理超时错误 - 增加超时时间"""
        new_plan = []
        for step in original_plan:
            new_step = step.copy()
            params = new_step.get("params", {}).copy()
            params["timeout"] = min(params.get("timeout", 60) * 2, 600)
            new_step["params"] = params
            new_plan.append(new_step)
        return new_plan

    def _handle_network_alternative(
        self,
        original_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """处理网络错误 - 添加重试延迟"""
        new_plan = []
        for step in original_plan:
            new_step = step.copy()
            params = new_step.get("params", {}).copy()
            params["retry_delay"] = 3
            new_step["params"] = params
            new_plan.append(new_step)
        return new_plan

    def _handle_permission_alternative(
        self,
        original_plan: List[Dict[str, Any]],
        state: "AgentState"
    ) -> List[Dict[str, Any]]:
        """处理权限错误 - 跳过相关步骤"""
        # 返回一个最小化计划
        return [
            {
                "step": 1,
                "action": "general_response",
                "params": {
                    "message": f"权限不足，无法完成任务。请检查权限设置。"
                },
                "description": "权限错误提示",
            }
        ]

    def _handle_generic_alternative(
        self,
        original_plan: List[Dict[str, Any]],
        state: "AgentState"
    ) -> List[Dict[str, Any]]:
        """处理通用错误 - 保留原计划"""
        return original_plan

    def preserve_successful_results(
        self,
        results: List[Dict[str, Any]],
        new_plan: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        保留已成功的步骤结果，避免重复执行

        检查新计划中是否有可以跳过的步骤（因为已经成功执行过）。
        """
        if not results or not new_plan:
            return new_plan

        # 找出成功的步骤
        successful_actions = {}
        for result in results:
            if isinstance(result, dict):
                step_result = result.get("result", {})
                if isinstance(step_result, dict) and step_result.get("success", False):
                    action = result.get("action")
                    successful_actions[action] = step_result.get("data")

        # 标记新计划中已成功的步骤
        preserved_plan = []
        for step in new_plan:
            step_copy = step.copy()
            action = step_copy.get("action")

            if action in successful_actions:
                # 标记为已成功，可以跳过
                step_copy["_already_completed"] = True
                step_copy["_cached_result"] = successful_actions[action]
                logger.info(f"[Replanner] 步骤 '{action}' 已完成，跳过执行")

            preserved_plan.append(step_copy)

        return preserved_plan

    def get_replan_strategy(self, retry_count: int) -> str:
        """
        获取当前重试次数对应的策略名称

        Args:
            retry_count: 当前重试次数

        Returns:
            str: 策略名称
        """
        strategies = {
            0: "adjust_params",
            1: "skip_failed",
            2: "fallback",
        }
        return strategies.get(retry_count, "fallback")
