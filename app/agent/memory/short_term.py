"""短期记忆模块"""

from typing import Dict, Any, Optional, List

from app.agent.memory.base import BaseMemory


class ConversationBuffer:
    """对话缓冲区 - 保存最近 N 条对话"""

    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages
        self.messages: List[Dict[str, Any]] = []

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加消息"""
        self.messages.append({
            "role": role,
            "content": content,
            "metadata": metadata or {}
        })

        if len(self.messages) > self.max_messages:
            self.messages.pop(0)

    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取消息"""
        if limit is None:
            return self.messages.copy()
        return self.messages[-limit:]

    def clear(self) -> None:
        """清空消息"""
        self.messages = []


class WorkingMemory(BaseMemory):
    """工作记忆 - 保存当前任务的中间状态"""

    def __init__(self, max_items: int = 10):
        self.max_items = max_items
        self._memory: Dict[str, Any] = {}

    async def add(self, key: str, value: Any) -> None:
        """添加记忆"""
        if len(self._memory) >= self.max_items and key not in self._memory:
            oldest_key = next(iter(self._memory))
            del self._memory[oldest_key]

        self._memory[key] = value

    async def get(self, key: str) -> Optional[Any]:
        """获取记忆"""
        return self._memory.get(key)

    async def remove(self, key: str) -> None:
        """删除记忆"""
        if key in self._memory:
            del self._memory[key]

    async def clear(self) -> None:
        """清空记忆"""
        self._memory = {}

    async def get_all(self) -> Dict[str, Any]:
        """获取所有记忆"""
        return self._memory.copy()


class ShortTermMemory:
    """短期记忆"""

    def __init__(self, max_messages: int = 50, max_items: int = 10):
        self.conversation = ConversationBuffer(max_messages=max_messages)
        self.working = WorkingMemory(max_items=max_items)

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加对话消息"""
        self.conversation.add_message(role, content, metadata)

    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取对话消息"""
        return self.conversation.get_messages(limit)

    async def set_working(self, key: str, value: Any) -> None:
        """设置工作记忆"""
        await self.working.add(key, value)

    async def get_working(self, key: str) -> Optional[Any]:
        """获取工作记忆"""
        return await self.working.get(key)

    async def clear_working(self) -> None:
        """清空工作记忆"""
        await self.working.clear()

    def clear_conversation(self) -> None:
        """清空对话"""
        self.conversation.clear()
