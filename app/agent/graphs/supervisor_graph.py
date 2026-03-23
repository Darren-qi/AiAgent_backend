"""监督图 - 支持步骤级评估和智能决策"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# 标准观察句式模板 - 基于真实执行情况生成
OBSERVATION_TEMPLATES = {
    # 执行结果相关
    "all_success": "已完整执行 {count} 个步骤：{action_summary}",
    "partial_success": "已完成 {success}/{total} 个步骤，{failed} 个失败：{failed_summary}",
    "all_failed": "{count} 个步骤均失败，需要重新规划",
    "step_success": "步骤 '{step}' 执行成功：{result_summary}",
    "step_failed": "步骤 '{step}' 执行失败：{error}",

    # 问题定位相关
    "issue_found": "定位到问题：{issue_location}，原因分析：{cause}",
    "issue_suspected": "初步判断问题出在 {location}，需要进一步验证",
    "root_cause_found": "找到根本原因：{root_cause}，位于 {location}",

    # 需求理解相关
    "intent_identified": "理解用户意图：{intent}，将围绕此目标规划执行",
    "intent_deep": "深入分析需求：{surface_req}，实际期望 {deep_req}",
    "requirement_clarified": "明确需求边界：{clarified_scope}，排除 {excluded_scope}",
    "context_recognized": "结合上下文 {context}，推断用户真实需求：{inferred_req}",
}


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
    - 智能重试判断
    """

    def __init__(self):
        self.confirmation_threshold = 0.7
        # 重试相关配置
        self.max_retries = 3
        self.timeout_retry_threshold = 3
        self.network_retry_threshold = 3

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

        # 预算耗尽检查
        if budget_status == "exhausted":
            return SupervisorDecision(
                action="reject",
                reason="预算已耗尽，拒绝新请求",
                next_step=None
            )

        # 预算降级检查
        if budget_status == "degraded":
            return SupervisorDecision(
                action="degrade",
                reason="预算接近阈值，启用降级策略",
                next_step=None
            )

        # 重试次数过多
        if retry_count >= self.max_retries:
            return SupervisorDecision(
                action="abort",
                reason="重试次数过多，终止任务",
                next_step=None
            )

        # 任务失败
        if not success and error:
            return SupervisorDecision(
                action="replan",
                reason=f"任务失败，需要重新规划: {error}",
                next_step=None
            )

        return SupervisorDecision(
            action="continue",
            reason="",  # 不发送无意义的机械性文字
            next_step=None
        )

    async def evaluate_step_results(
        self,
        results: List[Dict[str, Any]]
    ) -> SupervisorDecision:
        """
        评估一组步骤执行结果

        新增方法：评估整个迭代中所有步骤的执行情况。

        Args:
            results: 步骤执行结果列表

        Returns:
            监督决策: continue / replan / abort / done
        """
        if not results:
            return SupervisorDecision(
                action="continue",
                reason="无执行结果",
                next_step=None
            )

        # 统计结果
        total = len(results)
        successful = 0
        failed = 0
        errors = []
        action_names = []

        for result in results:
            if isinstance(result, dict):
                step_success = result.get("result", {}).get("success", True) if isinstance(result.get("result"), dict) else result.get("success", True)
                action = result.get("action", "未知步骤")
                action_names.append(action)

                if step_success:
                    successful += 1
                else:
                    failed += 1
                    error = result.get("result", {}).get("error") if isinstance(result.get("result"), dict) else result.get("error")
                    if error:
                        errors.append(error)
            elif isinstance(result, (list, tuple)):
                # 嵌套结果
                nested_result = await self.evaluate_step_results(result)
                if nested_result.action == "continue":
                    successful += 1
                else:
                    failed += 1

        # 根据真实执行情况生成观察消息
        if failed == 0:
            # 全部成功 - 根据不同场景生成不同消息
            if total == 1:
                reason = f"已执行步骤：{action_names[0]}"
            elif total <= 3:
                reason = f"已完成 {', '.join(action_names)}"
            else:
                reason = f"已执行全部 {total} 个步骤"
        elif successful == 0:
            # 全部失败
            reason = f"{total} 个步骤均未成功执行"
        else:
            # 部分失败 - 包含具体错误信息
            failed_details = []
            for i, result in enumerate(results):
                if isinstance(result, dict):
                    step_success = result.get("result", {}).get("success", True) if isinstance(result.get("result"), dict) else result.get("success", True)
                    action = result.get("action", "未知步骤")
                    if not step_success:
                        error = result.get("result", {}).get("error") if isinstance(result.get("result"), dict) else result.get("error")
                        if error:
                            failed_details.append(f"{action}: {error}")
                        else:
                            failed_details.append(action)
            if failed_details:
                reason = f"{successful} 个步骤成功，{failed} 个失败\n- " + "\n- ".join(failed_details)
            else:
                failed_actions = [action_names[i] for i, r in enumerate(results) if not (r.get("result", {}).get("success", True) if isinstance(r.get("result"), dict) else r.get("success", True))]
                reason = f"{successful} 个步骤成功，{failed} 个失败：{', '.join(failed_actions)}"

        return SupervisorDecision(
            action="continue" if failed == 0 else "replan",
            reason=reason,
            next_step=None
        )

    def should_retry(
        self,
        step_result: Dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 3
    ) -> bool:
        """
        判断是否应该重试当前步骤

        考虑：错误类型、重试次数、超时情况

        Args:
            step_result: 步骤执行结果
            retry_count: 当前重试次数
            max_retries: 最大重试次数

        Returns:
            bool: 是否应该重试
        """
        error = step_result.get("error", "")

        # 超过最大重试次数
        if retry_count >= max_retries:
            return False

        error_lower = error.lower()

        # 权限问题 → 不重试
        if any(x in error_lower for x in ["permission", "权限", "unauthorized", "forbidden"]):
            return False

        # 资源不存在 → 不重试
        if any(x in error_lower for x in ["not found", "404", "不存在", "不存在"]):
            return False

        # 客户端错误（业务错误）→ 不重试
        if any(x in error_lower for x in ["400", "bad request", "参数错误", "invalid"]):
            return False

        # 网络超时 → 重试
        if any(x in error_lower for x in ["timeout", "超时", "timed out"]):
            return retry_count < max_retries

        # 临时故障 → 重试
        if any(x in error_lower for x in ["temporary", "unavailable", "connection", "连接", "网络", "503", "502", "500"]):
            return retry_count < max_retries

        # 服务端错误 → 可选重试
        if any(x in error_lower for x in ["server error", "服务端错误"]):
            return retry_count < 2  # 最多重试2次

        # 未知错误 → 最多重试1次
        return retry_count < 1

    def make_budget_aware_decision(
        self,
        action: str,
        budget_percentage: float,
    ) -> str:
        """
        根据预算调整决策

        Args:
            action: 原始决策
            budget_percentage: 预算消耗百分比 (0-100)

        Returns:
            str: 调整后的决策
        """
        # 预算严重不足时，禁止重规划
        if budget_percentage >= 95 and action == "replan":
            return "abort"

        # 预算不足时，限制重试
        if budget_percentage >= 80 and action == "continue":
            return "degrade"

        return action

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
                {"action": "http_client", "params": {"timeout": 120}},
            ],
            "crawler": [
                {"action": "http_client", "params": {}},
                {"action": "skip", "params": {"reason": "爬虫失败"}},
            ],
            "search": [
                {"action": "search", "params": {"retry": True}},
                {"action": "general_response", "params": {"message": "搜索失败"}},
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
                action="continue",  # 改为 continue，让上层决定是否重试
                reason=f"步骤 '{step.get('action')}' 执行失败: {error}",
                next_step=None
            )

        # 检查结果数据是否为空或异常
        data = step_result.get("data")
        if data is None and step.get("action") not in ["general_response", "notification"]:
            logger.warning(f"[Supervisor] 步骤 {step.get('step')} 返回空数据")

        return SupervisorDecision(
            action="continue",
            reason=f"步骤 '{step.get('action')}' 执行成功",
            next_step=None
        )

    def format_observation(self, template_key: str, **kwargs) -> str:
        """
        格式化观察消息

        Args:
            template_key: 模板键名
            **kwargs: 模板变量

        Returns:
            格式化后的消息
        """
        template = OBSERVATION_TEMPLATES.get(template_key, "{message}")
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"[Supervisor] 模板变量缺失: {e}")
            return template

    def create_issue_observation(self, issue_location: str, cause: str = None) -> SupervisorDecision:
        """创建问题定位相关的观察"""
        return SupervisorDecision(
            action="continue",
            reason=self.format_observation(
                "issue_found" if cause else "issue_suspected",
                issue_location=issue_location,
                cause=cause or "",
                location=issue_location
            ),
            next_step=None
        )

    def create_intent_observation(self, intent: str, deep_req: str = None, context: str = None) -> SupervisorDecision:
        """创建需求理解相关的观察"""
        if deep_req:
            return SupervisorDecision(
                action="continue",
                reason=self.format_observation(
                    "intent_deep",
                    surface_req=intent,
                    deep_req=deep_req
                ),
                next_step=None
            )
        elif context:
            return SupervisorDecision(
                action="continue",
                reason=self.format_observation(
                    "context_recognized",
                    context=context,
                    inferred_req=intent
                ),
                next_step=None
            )
        else:
            return SupervisorDecision(
                action="continue",
                reason=self.format_observation(
                    "intent_identified",
                    intent=intent
                ),
                next_step=None
            )
