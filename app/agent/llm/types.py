"""LLM 类型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ModelProvider(str, Enum):
    """模型提供商枚举"""
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    ZHIPU = "zhipu"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    MINIMAX = "minimax"


class ModelCapability(str, Enum):
    """模型能力枚举"""
    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    VISION = "vision"
    FUNCTION_CALLING = "function_calling"


@dataclass
class ModelConfig:
    """模型配置"""
    name: str
    provider: ModelProvider
    display_name: str
    version: str = "v1"
    max_tokens: int = 4096
    context_window: int = 128000
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    capabilities: list[ModelCapability] = field(default_factory=list)
    enabled: bool = True
    api_key_env: str | None = None
    base_url_env: str | None = None
    model_id_env: str | None = None


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    provider: ModelProvider
    usage: dict[str, int]
    cost: float
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    raw_response: dict[str, Any] | None = None


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class ChatRequest:
    """聊天请求"""
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    user: str | None = None
    timeout: float | None = 60.0  # 请求超时时间（秒）
    # 用户级 API Key（2026-11-14）：非空时 provider 用它替代系统 key 计费。
    # 由 factory.chat 在 DeepSeek 选型且本 turn 用户填了自己 key 时注入。
    api_key: str | None = None
