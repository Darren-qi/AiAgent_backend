"""Agent 基类"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agent.llm.factory import LLMFactory
from app.agent.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Agent 类型枚举"""
    PLANNER = "planner"
    EXECUTOR = "executor"
    CRITIC = "critic"
    SUPERVISOR = "supervisor"
    COORDINATOR = "coordinator"
    GENERAL = "general"


@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    cost: float = 0.0


@dataclass
class AgentMessage:
    """Agent 消息"""
    agent_type: AgentType
    content: str
    from_agent: str = ""
    to_agent: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Agent 基类 - 所有 Agent 的抽象基类"""

    def __init__(
        self,
        agent_type: AgentType,
        name: str | None = None,
        system_prompt: str | None = None,
        llm_factory: LLMFactory | None = None,
        memory_manager: MemoryManager | None = None,
    ):
        self.agent_type = agent_type
        self.name = name or self.__class__.__name__
        self.system_prompt = system_prompt or self._get_default_system_prompt()
        self._llm_factory = llm_factory
        self._memory_manager = memory_manager
        self._message_history: list[AgentMessage] = []
        self._iteration_count = 0

    @property
    def llm_factory(self) -> LLMFactory:
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    @property
    def memory_manager(self) -> MemoryManager | None:
        return self._memory_manager

    @abstractmethod
    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示词"""
        pass

    @abstractmethod
    async def run(self, input_data: Any, context: dict[str, Any] | None = None) -> AgentResult:
        """
        执行 Agent 任务

        Args:
            input_data: 输入数据
            context: 执行上下文

        Returns:
            AgentResult
        """
        pass

    async def _call_llm(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        strategy: str = "balance",
        **kwargs
    ) -> str:
        """
        调用 LLM

        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            strategy: 路由策略
            **kwargs: 其他参数

        Returns:
            LLM 响应内容
        """
        self._iteration_count += 1

        try:
            response = await self.llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy=strategy,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            return response.content
        except Exception as e:
            logger.error(f"[{self.name}] LLM 调用失败: {e}")
            raise

    def send_message(
        self,
        to_agent: str,
        content: str,
        metadata: dict[str, Any] | None = None
    ) -> AgentMessage:
        """
        发送消息给其他 Agent

        Args:
            to_agent: 目标 Agent 名称
            content: 消息内容
            metadata: 附加元数据

        Returns:
            AgentMessage
        """
        message = AgentMessage(
            agent_type=self.agent_type,
            content=content,
            from_agent=self.name,
            to_agent=to_agent,
            metadata=metadata or {}
        )
        self._message_history.append(message)
        logger.debug(f"[{self.name}] 发送消息给 [{to_agent}]: {content[:100]}...")
        return message

    def receive_message(self, message: AgentMessage) -> None:
        """
        接收来自其他 Agent 的消息

        Args:
            message: 收到的消息
        """
        self._message_history.append(message)
        logger.debug(f"[{self.name}] 收到来自 [{message.from_agent}] 的消息: {message.content[:100]}...")

    def get_message_history(self) -> list[AgentMessage]:
        """获取消息历史"""
        return self._message_history.copy()

    def clear_history(self) -> None:
        """清空消息历史"""
        self._message_history.clear()
        self._iteration_count = 0

    def get_stats(self) -> dict[str, Any]:
        """获取 Agent 统计信息"""
        return {
            "name": self.name,
            "type": self.agent_type.value,
            "iterations": self._iteration_count,
            "message_count": len(self._message_history),
        }
