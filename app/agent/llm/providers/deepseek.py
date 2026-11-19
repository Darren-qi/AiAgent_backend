"""DeepSeek 模型实现"""

import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.agent.llm.providers.base import BaseLLMProvider
from app.agent.llm.types import (
    ChatRequest,
    LLMResponse,
    ModelConfig,
    ModelProvider,
)


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek 模型提供商"""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        api_key = os.environ.get(config.api_key_env or "DEEPSEEK_API_KEY", "")
        base_url = os.environ.get(config.base_url_env or "DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        self.base_url = base_url
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # 用户级 key 专属 client 缓存（2026-11-14）：key → 复用连接池的 client
        self._keyed_clients: dict[str, AsyncOpenAI] = {}

    def _client_for(self, api_key: str) -> AsyncOpenAI:
        """按用户 key 取（或建）专属 client，进程内按 key 复用。"""
        client = self._keyed_clients.get(api_key)
        if client is None:
            client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
            self._keyed_clients[api_key] = client
        return client

    def _pick_client(self, request: "ChatRequest") -> AsyncOpenAI:
        """request.api_key 非空（用户自己的 key）→ 用户 client，否则系统 client。"""
        uk = getattr(request, "api_key", None)
        return self._client_for(uk) if uk else self.client

    async def chat(self, request: ChatRequest) -> LLMResponse:
        """发送聊天请求"""
        start_time = time.time()

        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        kwargs: dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
            "timeout": httpx.Timeout(request.timeout or 60.0, connect=10.0),  # 读取超时 + 连接超时
        }

        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.top_p:
            kwargs["top_p"] = request.top_p
        if request.stop:
            kwargs["stop"] = request.stop
        if request.tools:
            kwargs["tools"] = request.tools

        try:
            response = await self._pick_client(request).chat.completions.create(**kwargs)

            latency_ms = (time.time() - start_time) * 1000

            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            return LLMResponse(
                content=response.choices[0].message.content or "",
                model=response.model,
                provider=ModelProvider.DEEPSEEK,
                usage=usage,
                cost=self.calculate_cost(usage),
                latency_ms=latency_ms,
                raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
            )
        except Exception as e:
            raise RuntimeError(f"DeepSeek API 调用失败: {e}")

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """流式聊天请求"""
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        kwargs: dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
            "stream": True,
        }

        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        if request.tools:
            kwargs["tools"] = request.tools

        async with self._pick_client(request).chat.completions.create(**kwargs) as stream:
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
