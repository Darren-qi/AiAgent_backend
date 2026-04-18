"""LLM 类型定义"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime


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
    capabilities: List[ModelCapability] = field(default_factory=list)
    enabled: bool = True
    api_key_env: Optional[str] = None
    base_url_env: Optional[str] = None
    model_id_env: Optional[str] = None


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    provider: ModelProvider
    usage: Dict[str, int]
    cost: float
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class ChatRequest:
    """聊天请求"""
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stop: Optional[List[str]] = None
    stream: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    user: Optional[str] = None
    timeout: Optional[float] = 60.0  # 请求超时时间（秒）
