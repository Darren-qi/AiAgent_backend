"""成本优先策略"""

from typing import List, Optional
from app.agent.llm.types import ModelConfig
from app.agent.llm.routers.base import BaseRouter


class CostStrategy(BaseRouter):
    """成本优先策略 - 选择最便宜的模型"""

    def select(self, available_models: List[ModelConfig]) -> Optional[ModelConfig]:
        """选择成本最低的模型"""
        if not available_models:
            return None

        sorted_models = sorted(
            available_models,
            key=lambda m: (m.input_cost_per_1k + m.output_cost_per_1k) / 2
        )

        return sorted_models[0] if sorted_models else None

    def get_strategy_name(self) -> str:
        return "cost"
