"""成本优先策略"""


from app.agent.llm.routers.base import BaseRouter
from app.agent.llm.types import ModelConfig


class CostStrategy(BaseRouter):
    """成本优先策略 - 选择最便宜的模型"""

    def select(self, available_models: list[ModelConfig]) -> ModelConfig | None:
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
