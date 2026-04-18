"""记忆管理器"""

from typing import Any, Dict, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory.pgsaver import PostgresSaver
from app.agent.memory.short_term import ShortTermMemory
from app.agent.memory.long_term import LongTermMemory


class MemoryManager:
    """记忆管理器 - 统一管理短期和长期记忆"""

    def __init__(
        self,
        session_id: str,
        db_session: Optional[AsyncSession] = None,
    ):
        self.session_id = session_id
        self.db_saver = PostgresSaver(db_session) if db_session else None

        self.short_term = ShortTermMemory(
            db_saver=self.db_saver,
            session_id=session_id,
        )
        self.long_term = LongTermMemory(
            db_saver=self.db_saver,
            session_id=session_id,
        )

    async def initialize(self) -> None:
        """初始化：从数据库加载已有数据到内存"""
        await self.short_term.load_from_db()
        await self.long_term.load_from_db()

    async def add_user_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加用户消息（异步保存到数据库）"""
        await self.short_term.add_message("user", content, metadata)

    async def add_assistant_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加助手消息（异步保存到数据库）"""
        await self.short_term.add_message("assistant", content, metadata)

    async def add_system_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """添加系统消息（异步保存到数据库）"""
        await self.short_term.add_message("system", content, metadata)

    def get_conversation_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.short_term.get_messages(limit)

    async def save_episode(self, event: Any) -> None:
        """保存事件到长期记忆"""
        import uuid
        episode_id = str(uuid.uuid4())
        await self.long_term.add_episode(episode_id, event)

    async def remember_fact(self, key: str, value: Any) -> None:
        """记住事实"""
        await self.long_term.add_fact(key, value)

    async def recall_fact(self, key: str) -> Optional[Any]:
        """回忆事实"""
        return await self.long_term.get_fact(key)

    async def search_memory(self, query: str) -> List[Dict[str, Any]]:
        """搜索记忆"""
        semantic_results = await self.long_term.search_facts(query)
        return semantic_results

    def clear_short_term(self) -> None:
        """清空短期记忆"""
        self.short_term.clear_conversation()

    async def clear_long_term(self) -> None:
        """清空长期记忆"""
        await self.long_term.semantic.clear()
        await self.long_term.episodic.clear()

    def get_context_for_llm(self, max_messages: int = 20) -> List[Dict[str, str]]:
        """获取用于 LLM 的上下文"""
        messages = self.get_conversation_history(limit=max_messages)
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    async def save_all_to_db(self) -> None:
        """手动保存所有记忆到数据库"""
        if not self.db_saver:
            return

        context = {
            "messages": self.short_term.get_messages(),
            "facts": await self.long_term.semantic.get_all(),
            "episodes": [
                {"id": e["id"], "event": e["event"]}
                for e in self.long_term.episodic.get_recent(limit=100)
            ],
            "working": await self.short_term.working.get_all(),
        }

        await self.db_saver.save_session_context(self.session_id, context)

    async def load_from_db(self) -> None:
        """从数据库加载所有记忆"""
        await self.initialize()
