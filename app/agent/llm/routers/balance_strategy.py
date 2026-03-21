"""平衡策略"""

from typing import List, Optional
from app.agent.llm.types import ModelConfig
from app.agent.llm.routers.base import BaseRouter


class BalanceStrategy(BaseRouter):
    """平衡策略 - 在成本和质量之间取得平衡"""

    def select(self, available_models: List[ModelConfig]) -> Optional[ModelConfig]:
        """选择性价比最高的模型"""
        if not available_models:
            return None

        scored_models = []
        for model in available_models:
            cost = (model.input_cost_per_1k + model.output_cost_per_1k) / 2
            capability = model.context_window / 128000

            if cost > 0:
                score = capability / cost
            else:
                score = capability * 1000

            scored_models.append((score, model))

        scored_models.sort(key=lambda x: x[0], reverse=True)

        return scored_models[0][1] if scored_models else None

    def get_strategy_name(self) -> str:
        return "balance"
