"""LLM 路由器基类"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.agent.llm.types import ModelConfig


class BaseRouter(ABC):
    """路由器基类"""

    @abstractmethod
    def select(self, available_models: List[ModelConfig]) -> Optional[ModelConfig]:
        """选择最佳模型"""
        pass

    @abstractmethod
    def get_strategy_name(self) -> str:
        """获取策略名称"""
        pass
