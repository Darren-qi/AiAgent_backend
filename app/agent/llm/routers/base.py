"""LLM 路由器基类"""

from abc import ABC, abstractmethod

from app.agent.llm.types import ModelConfig


class BaseRouter(ABC):
    """路由器基类"""

    @abstractmethod
    def select(self, available_models: list[ModelConfig]) -> ModelConfig | None:
        """选择最佳模型"""
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """获取策略名称"""
        pass
