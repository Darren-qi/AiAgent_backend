"""LLM 工厂类"""

import os
from typing import Dict, Any, Optional, Type

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.agent.llm.types import ModelConfig, ModelProvider, ChatRequest, LLMResponse
from app.agent.llm.router import ModelRouter
from app.agent.llm.budget_manager import BudgetManager


class LLMFactory:
    """LLM 工厂类 - 统一管理所有模型提供商"""

    _instance: Optional["LLMFactory"] = None
    _providers: Dict[ModelProvider, Type] = {}

    @classmethod
    def get_instance(cls, config: Optional[Dict[str, Any]] = None) -> "LLMFactory":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(config)
        elif config and not cls._instance._initialized:
            cls._instance.__init__(config)
        return cls._instance

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if self._initialized:
            return

        self.config = config or {}
        self.router = ModelRouter(self.config)
        self.budget_manager = BudgetManager()

        self._providers = {}
        self._provider_instances: Dict[ModelProvider, Any] = {}

        self._register_providers()
        self._initialized = True

    def _register_providers(self) -> None:
        """注册所有提供商"""
        from app.agent.llm.providers import BaseLLMProvider
        from app.agent.llm.providers.deepseek import DeepSeekProvider
        from app.agent.llm.providers.kimi import KimiProvider
        from app.agent.llm.providers.zhipu import ZhipuProvider
        from app.agent.llm.providers.openai import OpenAIProvider
        from app.agent.llm.providers.anthropic import AnthropicProvider
        from app.agent.llm.providers.gemini import GeminiProvider
        from app.agent.llm.providers.ollama import OllamaProvider
        from app.agent.llm.providers.minimax import MiniMaxProvider

        self._providers = {
            ModelProvider.DEEPSEEK: DeepSeekProvider,
            ModelProvider.KIMI: KimiProvider,
            ModelProvider.ZHIPU: ZhipuProvider,
            ModelProvider.OPENAI: OpenAIProvider,
            ModelProvider.ANTHROPIC: AnthropicProvider,
            ModelProvider.GEMINI: GeminiProvider,
            ModelProvider.OLLAMA: OllamaProvider,
            ModelProvider.MINIMAX: MiniMaxProvider,
        }

    def get_provider(self, provider: ModelProvider) -> Any:
        """获取提供商实例"""
        if provider not in self._provider_instances:
            provider_class = self._providers.get(provider)
            if not provider_class:
                raise ValueError(f"不支持的提供商: {provider}")

            models = self.router.get_available_models()
            model_config = next((m for m in models if m.provider == provider), None)

            if not model_config:
                raise ValueError(f"未配置 {provider.value} 模型")

            self._provider_instances[provider] = provider_class(model_config)

        return self._provider_instances[provider]

    async def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        strategy: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """发送聊天请求"""
        from app.agent.llm.types import ChatMessage

        chat_messages = [
            ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
            for m in messages
        ]

        request = ChatRequest(
            messages=chat_messages,
            model=model,
            **{k: v for k, v in kwargs.items() if k not in ("model",)}
        )

        selected_model = None

        if model:
            models = self.router.get_available_models()
            selected_model = next((m for m in models if m.name == model), None)

        if not selected_model:
            selected_model = self.router.select_model(strategy=strategy)

        if not selected_model:
            raise RuntimeError("没有可用的模型")

        estimated_cost = (selected_model.input_cost_per_1k + selected_model.output_cost_per_1k) / 2 * 1000
        allowed, status = await self.budget_manager.check_budget(estimated_cost)

        if not allowed:
            raise RuntimeError(f"预算不足，当前状态: {status.value}")

        provider = self.get_provider(selected_model.provider)
        response = await provider.chat(request)

        await self.budget_manager.record_usage(response.cost)

        return response

    def get_available_models(self) -> list:
        """获取可用模型列表"""
        return self.router.get_available_models()

    def get_budget_status(self):
        """获取预算状态"""
        return self.budget_manager.get_status()
