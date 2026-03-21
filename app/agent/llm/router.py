"""模型路由器"""

import os
from typing import Dict, List, Optional, Any

from app.agent.llm.types import ModelConfig, ModelProvider, ModelCapability
from app.agent.llm.routers.base import BaseRouter
from app.agent.llm.routers.cost_strategy import CostStrategy
from app.agent.llm.routers.quality_strategy import QualityStrategy
from app.agent.llm.routers.balance_strategy import BalanceStrategy


class ModelRouter:
    """模型路由器"""

    PROVIDER_CLASSES = {
        ModelProvider.DEEPSEEK: "app.agent.llm.providers.deepseek.DeepSeekProvider",
        ModelProvider.KIMI: "app.agent.llm.providers.kimi.KimiProvider",
        ModelProvider.ZHIPU: "app.agent.llm.providers.zhipu.ZhipuProvider",
        ModelProvider.OPENAI: "app.agent.llm.providers.openai.OpenAIProvider",
        ModelProvider.ANTHROPIC: "app.agent.llm.providers.anthropic.AnthropicProvider",
        ModelProvider.GEMINI: "app.agent.llm.providers.gemini.GeminiProvider",
        ModelProvider.OLLAMA: "app.agent.llm.providers.ollama.OllamaProvider",
        ModelProvider.MINIMAX: "app.agent.llm.providers.minimax.MiniMaxProvider",
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.strategies: Dict[str, BaseRouter] = {
            "cost": CostStrategy(),
            "quality": QualityStrategy(),
            "balance": BalanceStrategy(),
        }
        self.default_strategy = config.get("default_strategy", "balance")

    def get_available_models(self) -> List[ModelConfig]:
        """获取所有可用的模型配置"""
        models = []

        allowed = set(m.strip() for m in self.config.get("allowed_models", "").split(",") if m.strip())
        blocked = set(m.strip() for m in self.config.get("blocked_models", "").split(",") if m.strip())

        for provider in ModelProvider:
            api_key = os.environ.get(f"{provider.value.upper()}_API_KEY")
            if not api_key:
                continue

            model_name = os.environ.get(f"{provider.value.upper()}_MODEL", "")
            base_url = os.environ.get(f"{provider.value.upper()}_BASE_URL", "")

            if allowed and model_name not in allowed:
                continue
            if model_name in blocked:
                continue

            models.append(self._create_model_config(provider, model_name, base_url))

        return models

    def _create_model_config(self, provider: ModelProvider, model_name: str, base_url: str) -> ModelConfig:
        """创建模型配置"""
        cost_info = self._get_model_cost(provider)

        return ModelConfig(
            name=model_name,
            provider=provider,
            display_name=model_name,
            api_key_env=f"{provider.value.upper()}_API_KEY",
            base_url_env=f"{provider.value.upper()}_BASE_URL",
            model_id_env=f"{provider.value.upper()}_MODEL",
            input_cost_per_1k=cost_info["input"],
            output_cost_per_1k=cost_info["output"],
            capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
        )

    def _get_model_cost(self, provider: ModelProvider) -> Dict[str, float]:
        """获取模型成本信息"""
        costs = {
            ModelProvider.DEEPSEEK: {"input": 0.0001, "output": 0.0003},
            ModelProvider.KIMI: {"input": 0.001, "output": 0.004},
            ModelProvider.ZHIPU: {"input": 0.0001, "output": 0.0003},
            ModelProvider.OPENAI: {"input": 0.01, "output": 0.03},
            ModelProvider.ANTHROPIC: {"input": 0.015, "output": 0.075},
            ModelProvider.GEMINI: {"input": 0.000125, "output": 0.0005},
            ModelProvider.OLLAMA: {"input": 0.0, "output": 0.0},
            ModelProvider.MINIMAX: {"input": 0.0001, "output": 0.0002},
        }
        return costs.get(provider, {"input": 0.0, "output": 0.0})

    def select_model(
        self,
        strategy: Optional[str] = None,
        required_capabilities: Optional[List[ModelCapability]] = None,
    ) -> Optional[ModelConfig]:
        """根据策略选择模型"""
        strategy_name = strategy or self.default_strategy

        router = self.strategies.get(strategy_name)
        if not router:
            router = self.strategies["balance"]

        available_models = self.get_available_models()

        if required_capabilities:
            available_models = [
                m for m in available_models
                if all(cap in m.capabilities for cap in required_capabilities)
            ]

        return router.select(available_models)
