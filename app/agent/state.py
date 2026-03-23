"""统一状态管理模块"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class ExecutionStatus(str, Enum):
    """执行状态枚举"""
    PENDING = "pending"           # 等待执行
    RUNNING = "running"          # 执行中
    SUCCEEDED = "succeeded"      # 成功完成
    FAILED = "failed"           # 执行失败
    TERMINATED = "terminated"    # 被终止
    ABORTED = "aborted"          # 异常中止


class LoopDetectionResult(str, Enum):
    """循环检测结果枚举"""
    NORMAL = "normal"           # 正常执行
    INFINITE_LOOP = "infinite_loop"       # 死循环
    OSCILLATION = "oscillation"           # 振荡
    NO_PROGRESS = "no_progress"           # 无进展
    BUDGET_EXHAUSTED = "budget_exhausted" # 预算耗尽


@dataclass
class ExecutionContext:
    """
    统一执行上下文 - 贯穿整个执行生命周期

    替代原有的分散在 state.context 中的各种计数器，
    提供统一的执行状态管理。
    """
    # 迭代控制
    iteration: int = 0                    # 当前迭代次数 (从0开始)
    max_iterations: int = 15             # 最大迭代次数 (调整为15)
    iteration_warning_threshold: int = 10 # 迭代警告阈值

    # 重试控制
    retry_count: int = 0                  # 当前步骤重试次数
    max_retries: int = 3                 # 单步骤最大重试次数

    # 步骤跟踪
    total_steps: int = 0                 # 总步骤数
    completed_steps: int = 0             # 已完成步骤数
    failed_steps: List[int] = field(default_factory=list)  # 失败的步骤索引

    # 计划历史 (用于循环检测)
    plan_history: List[List[Dict[str, Any]]] = field(default_factory=list)  # 历史计划
    result_history: List[Dict[str, Any]] = field(default_factory=list)  # 历史结果

    # 替代方案
    alternate_plans: List[List[Dict[str, Any]]] = field(default_factory=list)  # 替代计划历史
    recovery_attempts: int = 0            # 恢复尝试次数

    # 执行配置
    parallel_enabled: bool = True         # 是否启用并行执行
    force_single_step: bool = False      # 强制单步执行（用于调试）
    task_path: Optional[str] = None     # 任务文件存储路径 (AiAgent/tasks/项目名_时间戳/)

    # 超时配置 (单位: 秒)
    default_step_timeout: int = 300      # 默认单步超时: 5分钟 (原60秒)
    max_step_timeout: int = 600           # 最大超时: 10分钟
    http_step_timeout: int = 600         # HTTP类步骤超时: 10分钟

    # 状态
    status: ExecutionStatus = ExecutionStatus.PENDING
    last_error: Optional[str] = None     # 最后一次错误信息
    termination_reason: Optional[str] = None  # 终止原因

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "parallel_enabled": self.parallel_enabled,
            "status": self.status.value,
            "last_error": self.last_error,
        }

    def should_warn_iteration(self) -> bool:
        """检查是否应该发出迭代警告"""
        return self.iteration >= self.iteration_warning_threshold

    def can_retry(self) -> bool:
        """是否可以重试"""
        return self.retry_count < self.max_retries

    def can_iterate(self) -> bool:
        """是否可以继续迭代"""
        return self.iteration < self.max_iterations

    def record_plan(self, plan: List[Dict[str, Any]]) -> None:
        """记录计划到历史"""
        self.plan_history.append(plan)

    def record_result(self, result: Dict[str, Any]) -> None:
        """记录结果到历史"""
        self.result_history.append(result)

    def increment_iteration(self) -> None:
        """增加迭代计数"""
        self.iteration += 1

    def increment_retry(self) -> None:
        """增加重试计数"""
        self.retry_count += 1

    def reset_retry(self) -> None:
        """重置重试计数"""
        self.retry_count = 0

    def get_timeout_for_action(self, action: str) -> int:
        """根据动作类型获取超时时间"""
        if action in ("http_client", "crawler", "search"):
            return self.http_step_timeout
        return self.default_step_timeout


@dataclass
class ObservationResult:
    """
    观察结果 - Observation 阶段的输出

    用于在每次迭代后评估执行情况，决定下一步行动。
    """
    loop_status: LoopDetectionResult = LoopDetectionResult.NORMAL
    should_continue: bool = True
    should_replan: bool = False
    should_terminate: bool = False
    termination_reason: Optional[str] = None
    fallback_action: Optional[str] = None  # terminate时的兜底动作
    message: str = ""


class LoopDetector:
    """
    死循环检测器

    通过分析计划历史和结果历史，检测异常执行模式。
    """

    def __init__(self):
        self.exact_loop_threshold = 3      # 同一计划执行次数阈值
        self.oscillation_threshold = 2      # 振荡次数阈值
        self.no_progress_threshold = 3     # 无进展次数阈值

    def detect(
        self,
        context: ExecutionContext,
        current_plan: List[Dict[str, Any]]
    ) -> ObservationResult:
        """
        检测是否为死循环场景

        Args:
            context: 执行上下文
            current_plan: 当前计划

        Returns:
            ObservationResult: 观察结果
        """
        # 1. 精确循环检测
        loop_result = self._detect_exact_loop(context.plan_history, current_plan)
        if loop_result:
            return ObservationResult(
                loop_status=LoopDetectionResult.INFINITE_LOOP,
                should_continue=False,
                should_terminate=True,
                termination_reason="检测到死循环: 同一计划重复执行",
                fallback_action="return_last_result",
                message=f"计划 '{self._plan_summary(current_plan)}' 已执行 {self.exact_loop_threshold} 次"
            )

        # 2. 振荡检测
        oscillation_result = self._detect_oscillation(context.plan_history)
        if oscillation_result:
            return ObservationResult(
                loop_status=LoopDetectionResult.OSCILLATION,
                should_continue=False,
                should_terminate=True,
                termination_reason="检测到振荡: 计划反复切换",
                fallback_action="merge_last_two_results",
                message="检测到计划在两个方案间反复切换"
            )

        # 3. 无进展检测
        no_progress_result = self._detect_no_progress(context.result_history)
        if no_progress_result:
            return ObservationResult(
                loop_status=LoopDetectionResult.NO_PROGRESS,
                should_continue=False,
                should_terminate=True,
                termination_reason="连续多次迭代无进展",
                fallback_action="summarize_partial_results",
                message="连续多次迭代结果完全相同"
            )

        return ObservationResult(
            loop_status=LoopDetectionResult.NORMAL,
            should_continue=True,
            message=""  # 不发送无意义的机械性文字
        )

    def _detect_exact_loop(
        self,
        plan_history: List[List[Dict[str, Any]]],
        current_plan: List[Dict[str, Any]]
    ) -> bool:
        """检测精确循环: 相同计划执行超过阈值"""
        if len(plan_history) < self.exact_loop_threshold:
            return False

        # 计算当前计划与历史的匹配次数
        match_count = sum(
            1 for plan in plan_history
            if self._plans_equal(plan, current_plan)
        )

        # 包含当前计划
        return (match_count + 1) >= self.exact_loop_threshold

    def _detect_oscillation(
        self,
        plan_history: List[List[Dict[str, Any]]]
    ) -> bool:
        """
        检测振荡: 两个计划交替执行

        例如: [A, B, A, B, A, B] -> 振荡
        """
        if len(plan_history) < 4:
            return False

        # 检查最后几个计划是否在两个之间交替
        recent = plan_history[-4:]

        # 提取唯一的计划
        unique_plans = []
        for plan in recent:
            is_new = True
            for existing in unique_plans:
                if self._plans_equal(plan, existing):
                    is_new = False
                    break
            if is_new:
                unique_plans.append(plan)

        # 如果只有2个计划且模式是ABAB，则为振荡
        if len(unique_plans) == 2:
            last_4 = plan_history[-4:]
            pattern = [
                self._find_plan_index(last_4[0], plan_history),
                self._find_plan_index(last_4[1], plan_history),
                self._find_plan_index(last_4[2], plan_history),
                self._find_plan_index(last_4[3], plan_history),
            ]
            # 检查是否为ABAB或BABA模式
            if pattern[0] != pattern[1] and pattern[1] == pattern[2] and pattern[2] != pattern[3]:
                # 进一步确认交替模式
                alternating = True
                for i in range(len(pattern) - 1):
                    if pattern[i] == pattern[i + 1]:
                        alternating = False
                        break
                if alternating:
                    return True

        return False

    def _detect_no_progress(
        self,
        result_history: List[Dict[str, Any]]
    ) -> bool:
        """
        检测无进展: 连续多次迭代结果完全相同
        """
        if len(result_history) < self.no_progress_threshold:
            return False

        # 检查最后N个结果是否完全相同
        recent = result_history[-self.no_progress_threshold:]

        if not recent:
            return False

        # 比较所有结果的 data 字段
        first_data = self._normalize_result_data(recent[0])
        for result in recent[1:]:
            if self._normalize_result_data(result) != first_data:
                return False

        return True

    def _plans_equal(
        self,
        plan1: List[Dict[str, Any]],
        plan2: List[Dict[str, Any]]
    ) -> bool:
        """比较两个计划是否相同"""
        if len(plan1) != len(plan2):
            return False

        for step1, step2 in zip(plan1, plan2):
            # 比较关键字段
            if step1.get("action") != step2.get("action"):
                return False
            if step1.get("params") != step2.get("params"):
                return False

        return True

    def _find_plan_index(
        self,
        plan: List[Dict[str, Any]],
        plan_history: List[List[Dict[str, Any]]]
    ) -> int:
        """查找计划在历史中的索引"""
        for i, historical in enumerate(plan_history):
            if self._plans_equal(plan, historical):
                return i
        return -1

    def _normalize_result_data(self, result: Dict[str, Any]) -> str:
        """标准化结果数据用于比较"""
        data = result.get("data") or result.get("result", {}).get("data")
        if data is None:
            return "null"
        if isinstance(data, str):
            # 截断长字符串
            return data[:500] if len(data) > 500 else data
        # 对于复杂对象，转换为JSON
        import json
        try:
            return json.dumps(data, sort_keys=True, default=str)
        except:
            return str(data)

    def _plan_summary(self, plan: List[Dict[str, Any]]) -> str:
        """生成计划摘要"""
        actions = [step.get("action", "unknown") for step in plan]
        return " -> ".join(actions)


# 全局实例
default_loop_detector = LoopDetector()


def create_execution_context(
    max_iterations: int = 15,
    parallel_enabled: bool = True,
    max_retries: int = 3,
    **kwargs
) -> ExecutionContext:
    """
    创建执行上下文的工厂函数

    Args:
        max_iterations: 最大迭代次数 (默认15)
        parallel_enabled: 是否启用并行 (默认True)
        max_retries: 最大重试次数 (默认3)
        **kwargs: 其他配置参数（如 default_step_timeout, http_step_timeout 等）

    Returns:
        ExecutionContext: 配置好的执行上下文
    """
    # 从 kwargs 中提取 ExecutionContext 的其他字段
    # 避免与命名参数冲突
    context_kwargs = {}

    # 这些参数直接通过命名参数传递，不从 kwargs 中取
    forbidden_keys = {'max_iterations', 'parallel_enabled', 'max_retries'}

    for key, value in kwargs.items():
        if key not in forbidden_keys:
            context_kwargs[key] = value

    return ExecutionContext(
        max_iterations=max_iterations,
        parallel_enabled=parallel_enabled,
        max_retries=max_retries,
        **context_kwargs
    )
