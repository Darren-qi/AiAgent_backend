"""Ollama 本地模型实现"""

import os
import time
from typing import AsyncIterator, Dict, Any

import httpx
from openai import AsyncOpenAI

from app.agent.llm.providers.base import BaseLLMProvider
from app.agent.llm.types import (
    ChatRequest,
    LLMResponse,
    ModelConfig,
    ModelProvider,
)


class OllamaProvider(BaseLLMProvider):
    """Ollama 本地模型提供商"""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        base_url = os.environ.get(config.base_url_env or "OLLAMA_BASE_URL", "http://localhost:11434")

        self.client = AsyncOpenAI(
            api_key="ollama",
            base_url=f"{base_url}/v1"
        )

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
            provider=ModelProvider.OLLAMA,
            usage=usage,
            cost=0.0,
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
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.client.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False
