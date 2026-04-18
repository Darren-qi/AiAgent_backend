"""短期记忆模块"""

from typing import Any, Dict, Optional, List

from app.agent.memory.base import BaseMemory
from app.agent.memory.pgsaver import PostgresSaver


class ConversationBuffer:
    """对话缓冲区 - 保存最近 N 条对话"""

    def __init__(
        self,
        max_messages: int = 50,
        db_saver: Optional[PostgresSaver] = None,
    ):
        self.max_messages = max_messages
        self.db_saver = db_saver
        self._messages: List[Dict[str, Any]] = []
        self._session_id: Optional[str] = None

    def set_session(self, session_id: str) -> None:
        """设置会话ID"""
        self._session_id = session_id

    async def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加消息（同步到内存，异步保存到数据库）"""
        self._messages.append({
            "role": role,
            "content": content,
            "metadata": metadata or {},
        })

        if len(self._messages) > self.max_messages:
            self._messages.pop(0)

        # 异步保存到数据库（不再使用 fire-and-forget 的 create_task）
        if self.db_saver and self._session_id:
            await self.db_saver.save_message(
                session_id=self._session_id,
                role=role,
                content=content,
                metadata=metadata,
            )

    def get_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取消息"""
        if limit is None:
            return self._messages.copy()
        return self._messages[-limit:]

    def clear(self) -> None:
        """清空消息"""
        self._messages = []


class WorkingMemory(BaseMemory):
    """工作记忆 - 保存当前任务的中间状态"""

    def __init__(
        self,
        max_items: int = 10,
        db_saver: Optional[PostgresSaver] = None,
    ):
        self.max_items = max_items
        self.db_saver = db_saver
        self._memory: Dict[str, Any] = {}
        self._session_id: Optional[str] = None

    def set_session(self, session_id: str) -> None:
        """设置会话ID"""
        self._session_id = session_id

    async def add(self, key: str, value: Any) -> None:
        """添加记忆"""
        if len(self._memory) >= self.max_items and key not in self._memory:
            oldest_key = next(iter(self._memory))
            del self._memory[oldest_key]

        self._memory[key] = value

        if self.db_saver and self._session_id:
            await self.db_saver.save_working(
                session_id=self._session_id,
                memory_key=key,
                memory_value=value,
            )

    async def get(self, key: str) -> Optional[Any]:
        """获取记忆"""
        return self._memory.get(key)

    async def remove(self, key: str) -> None:
        """删除记忆"""
        if key in self._memory:
            del self._memory[key]

        if self.db_saver and self._session_id:
            await self.db_saver.delete_working(
                session_id=self._session_id,
                memory_key=key,
            )

    async def clear(self) -> None:
        """清空记忆"""
        self._memory = {}

    async def get_all(self) -> Dict[str, Any]:
        """获取所有记忆"""
        return self._memory.copy()


class ShortTermMemory:
    """短期记忆"""

    def __init__(
        self,
        max_messages: int = 50,
        max_items: int = 10,
        db_saver: Optional[PostgresSaver] = None,
        session_id: Optional[str] = None,
    ):
        self.conversation = ConversationBuffer(
            max_messages=max_messages,
            db_saver=db_saver,
        )
        self.working = WorkingMemory(max_items=max_items, db_saver=db_saver)
        if session_id:
            self.set_session(session_id)

    def set_session(self, session_id: str) -> None:
        """设置会话ID并加载持久化数据"""
        self.conversation.set_session(session_id)
        self.working.set_session(session_id)

    async def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加对话消息"""
        await self.conversation.add_message(role, content, metadata)

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

    async def load_from_db(self) -> None:
        """从数据库加载数据到内存"""
        if self.conversation.db_saver and self.conversation._session_id:
            messages = await self.conversation.db_saver.get_recent_messages(
                self.conversation._session_id,
                limit=self.conversation.max_messages,
            )
            for msg in messages:
                self.conversation._messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                    "metadata": msg.get("metadata", {}),
                })

        if self.working.db_saver and self.working._session_id:
            working_data = await self.working.db_saver.get_all_working(
                self.working._session_id
            )
            self.working._memory = working_data
