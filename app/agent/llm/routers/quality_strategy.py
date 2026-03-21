"""质量优先策略"""

from typing import List, Optional
from app.agent.llm.types import ModelConfig
from app.agent.llm.routers.base import BaseRouter


class QualityStrategy(BaseRouter):
    """质量优先策略 - 选择能力最强的模型"""

    def select(self, available_models: List[ModelConfig]) -> Optional[ModelConfig]:
        """选择能力最强的模型"""
        if not available_models:
            return None

        sorted_models = sorted(
            available_models,
            key=lambda m: m.context_window,
            reverse=True
        )

        return sorted_models[0] if sorted_models else None

    def get_strategy_name(self) -> str:
        return "quality"
