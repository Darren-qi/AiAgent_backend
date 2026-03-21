"""Anthropic (Claude) 模型实现"""

import os
import time
from typing import AsyncIterator, Dict, Any

import httpx
from anthropic import AsyncAnthropic

from app.agent.llm.providers.base import BaseLLMProvider
from app.agent.llm.types import (
    ChatRequest,
    LLMResponse,
    ModelConfig,
    ModelProvider,
)


class AnthropicProvider(BaseLLMProvider):
    """Anthropic (Claude) 模型提供商"""

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        api_key = os.environ.get(config.api_key_env or "ANTHROPIC_API_KEY", "")

        self.client = AsyncAnthropic(api_key=api_key)

    async def chat(self, request: ChatRequest) -> LLMResponse:
        """发送聊天请求"""
        start_time = time.time()

        system_prompt = ""
        messages = []

        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        kwargs: Dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        else:
            kwargs["max_tokens"] = 1024

        response = await self.client.messages.create(**kwargs)
        latency_ms = (time.time() - start_time) * 1000

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        content = ""
        if response.content and isinstance(response.content, list):
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text
                elif isinstance(block, dict) and block.get("type") == "text":
                    content += block.get("text", "")

        return LLMResponse(
            content=content,
            model=response.model,
            provider=ModelProvider.ANTHROPIC,
            usage=usage,
            cost=self.calculate_cost(usage),
            latency_ms=latency_ms,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        """流式聊天请求"""
        system_prompt = ""
        messages = []

        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        kwargs: Dict[str, Any] = {
            "model": self.config.name,
            "messages": messages,
            "temperature": request.temperature,
            "stream": True,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        else:
            kwargs["max_tokens"] = 1024

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def validate_connection(self) -> bool:
        """验证连接是否正常"""
        try:
            await self.client.messages.count()
            return True
        except Exception:
            return False
