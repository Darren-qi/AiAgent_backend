"""Google Gemini 模型实现"""

import os
import time
from typing import AsyncIterator, Dict, Any, Optional

import httpx
from openai import AsyncOpenAI

from app.agent.llm.providers.base import BaseLLMProvider
from app.agent.llm.types import (
    ChatRequest,
    LLMResponse,
    ModelConfig,
    ModelProvider,
)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini 模型提供商"""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        api_key = os.environ.get(config.api_key_env or "GEMINI_API_KEY", "")
        base_url = os.environ.get(
            config.base_url_env or "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(self, request: ChatRequest) -> LLMResponse:
        """发送聊天请求"""
        start_time = time.time()

        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        kwargs: Dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
        }

        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        latency_ms = (time.time() - start_time) * 1000

        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }

        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            provider=ModelProvider.GEMINI,
            usage=usage,
            cost=self.calculate_cost(usage),
            latency_ms=latency_ms,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """流式聊天请求"""
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        kwargs: Dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
            "stream": True,
        }

        async with self.client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    async def validate_connection(self) -> bool:
        """验证连接是否正常"""
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False
