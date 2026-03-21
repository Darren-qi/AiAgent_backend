"""LLM 基类"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, Optional

from app.agent.llm.types import ChatRequest, LLMResponse, ModelConfig


class BaseLLMProvider(ABC):
    """LLM 提供商基类"""

    def __init__(self, config: ModelConfig):
        self.config = config

    @abstractmethod
    async def chat(self, request: ChatRequest) -> LLMResponse:
        """发送聊天请求"""
        pass

    @abstractmethod
    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """流式聊天请求"""
        pass

    @abstractmethod
    async def validate_connection(self) -> bool:
        """验证连接是否正常"""
        pass

    def calculate_cost(self, usage: Dict[str, int]) -> float:
        """计算请求成本"""
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        input_cost = (input_tokens / 1000) * self.config.input_cost_per_1k
        output_cost = (output_tokens / 1000) * self.config.output_cost_per_1k

        return input_cost + output_cost
