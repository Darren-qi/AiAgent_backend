"""LLM 预算管理器"""

import os
from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum


class BudgetStatus(str, Enum):
    """预算状态"""
    NORMAL = "normal"
    WARNING = "warning"
    DEGRADED = "degraded"
    EXHAUSTED = "exhausted"


@dataclass
class BudgetInfo:
    """预算信息"""
    daily_limit: float
    monthly_limit: float
    daily_used: float = 0.0
    monthly_used: float = 0.0
    warning_threshold: float = 80.0
    degradation_threshold: float = 95.0
    status: BudgetStatus = BudgetStatus.NORMAL
    last_reset_daily: datetime = field(default_factory=datetime.now)
    last_reset_monthly: datetime = field(default_factory=datetime.now)


class BudgetManager:
    """预算管理器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        self.daily_limit = float(os.environ.get("BUDGET_DAILY_LIMIT", "10.0"))
        self.monthly_limit = float(os.environ.get("BUDGET_MONTHLY_LIMIT", "100.0"))
        self.warning_threshold = float(os.environ.get("BUDGET_WARNING_THRESHOLD", "80.0"))
        self.degradation_threshold = float(os.environ.get("BUDGET_DEGRADATION_THRESHOLD", "95.0"))
        self.reject_on_exhausted = os.environ.get("BUDGET_REJECT_ON_EXHAUSTED", "true").lower() == "true"

        self._budget_info = BudgetInfo(
            daily_limit=self.daily_limit,
            monthly_limit=self.monthly_limit,
            warning_threshold=self.warning_threshold,
            degradation_threshold=self.degradation_threshold,
        )

    async def check_budget(self, estimated_cost: float) -> tuple[bool, BudgetStatus]:
        """检查预算是否足够"""
        self._check_reset()

        daily_remaining = self.daily_limit - self._budget_info.daily_used
        monthly_remaining = self.monthly_limit - self._budget_info.monthly_used

        daily_percentage = (self._budget_info.daily_used / self.daily_limit) * 100
        monthly_percentage = (self._budget_info.monthly_used / self.monthly_limit) * 100

        if daily_percentage >= 100 or monthly_percentage >= 100:
            self._budget_info.status = BudgetStatus.EXHAUSTED
            return not self.reject_on_exhausted, BudgetStatus.EXHAUSTED

        if daily_percentage >= self.degradation_threshold or monthly_percentage >= self.degradation_threshold:
            self._budget_info.status = BudgetStatus.DEGRADED
        elif daily_percentage >= self.warning_threshold or monthly_percentage >= self.warning_threshold:
            self._budget_info.status = BudgetStatus.WARNING
        else:
            self._budget_info.status = BudgetStatus.NORMAL

        if estimated_cost > min(daily_remaining, monthly_remaining):
            return False, self._budget_info.status

        return True, self._budget_info.status

    async def record_usage(self, cost: float) -> None:
        """记录使用量"""
        self._budget_info.daily_used += cost
        self._budget_info.monthly_used += cost

    def get_status(self) -> BudgetInfo:
        """获取预算状态"""
        self._check_reset()
        return self._budget_info

    def _check_reset(self) -> None:
        """检查是否需要重置"""
        now = datetime.now()

        if now.date() > self._budget_info.last_reset_daily.date():
            self._budget_info.daily_used = 0.0
            self._budget_info.last_reset_daily = now

        if now.month != self._budget_info.last_reset_monthly.month or now.year != self._budget_info.last_reset_monthly.year:
            self._budget_info.monthly_used = 0.0
            self._budget_info.last_reset_monthly = now

    async def reset_daily(self) -> None:
        """重置每日预算"""
        self._budget_info.daily_used = 0.0
        self._budget_info.last_reset_daily = datetime.now()

    async def reset_monthly(self) -> None:
        """重置每月预算"""
        self._budget_info.monthly_used = 0.0
        self._budget_info.last_reset_monthly = datetime.now()
