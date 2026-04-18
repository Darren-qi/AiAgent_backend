"""
PostgreSQL 记忆持久化模块

提供异步的数据库操作，将记忆数据持久化到 PostgreSQL。
支持对话消息、语义事实、情景事件和工作记忆的存储与检索。
"""

import logging
from typing import Any, Dict, List, Optional, TypeVar
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory.models import (
    ConversationMessage,
    EpisodicEvent,
    SemanticFact,
    WorkingMemory,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PostgresSaver:
    """
    PostgreSQL 记忆持久化器

    提供统一的数据库操作接口，支持：
    - 对话消息的增删查
    - 语义事实的增删改查
    - 情景事件的增删查
    - 工作记忆的增删改查
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """保存对话消息，返回消息ID"""
        seq_result = await self._session.execute(
            select(ConversationMessage.sequence)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.sequence.desc())
            .limit(1)
        )
        last_seq = seq_result.scalar() or 0

        message = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata,
            sequence=last_seq + 1,
        )
        self._session.add(message)
        await self._session.flush()
        logger.info(f"[PostgresSaver] 保存消息: session={session_id}, role={role}, seq={last_seq + 1}")
        return message.id

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """获取对话消息列表"""
        query = (
            select(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.sequence)
            .offset(offset)
        )
        if limit:
            query = query.limit(limit)

        result = await self._session.execute(query)
        messages = result.scalars().all()

        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "metadata": m.message_metadata,
                "sequence": m.sequence,
                "created_at": m.created_at,
            }
            for m in messages
        ]

    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取最近的 N 条消息"""
        messages = await self.get_messages(session_id, limit=limit)
        return messages[-limit:] if messages else []

    async def clear_messages(self, session_id: str) -> int:
        """清空会话的所有消息，返回删除数量"""
        result = await self._session.execute(
            delete(ConversationMessage)
            .where(ConversationMessage.session_id == session_id)
        )
        return result.rowcount or 0

    async def save_fact(
        self,
        session_id: str,
        fact_key: str,
        fact_value: Any,
    ) -> int:
        """保存或更新语义事实，使用 upsert 策略"""
        stmt = insert(SemanticFact).values(
            session_id=session_id,
            fact_key=fact_key,
            fact_value=fact_value if isinstance(fact_value, dict) else {"value": fact_value},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["session_id", "fact_key"],
            set_={
                "fact_value": stmt.excluded.fact_value,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.inserted_primary_key[0] if result.inserted_primary_key else 0

    async def get_fact(
        self,
        session_id: str,
        fact_key: str,
    ) -> Optional[Dict[str, Any]]:
        """获取单个语义事实"""
        result = await self._session.execute(
            select(SemanticFact).where(
                SemanticFact.session_id == session_id,
                SemanticFact.fact_key == fact_key,
            )
        )
        fact = result.scalar_one_or_none()
        if fact:
            return {"key": fact.fact_key, "value": fact.fact_value}
        return None

    async def get_all_facts(self, session_id: str) -> Dict[str, Any]:
        """获取会话的所有语义事实"""
        result = await self._session.execute(
            select(SemanticFact).where(SemanticFact.session_id == session_id)
        )
        facts = result.scalars().all()
        return {f.fact_key: f.fact_value for f in facts}

    async def delete_fact(self, session_id: str, fact_key: str) -> bool:
        """删除语义事实"""
        result = await self._session.execute(
            delete(SemanticFact).where(
                SemanticFact.session_id == session_id,
                SemanticFact.fact_key == fact_key,
            )
        )
        return (result.rowcount or 0) > 0

    async def clear_facts(self, session_id: str) -> int:
        """清空会话的所有语义事实"""
        result = await self._session.execute(
            delete(SemanticFact).where(SemanticFact.session_id == session_id)
        )
        return result.rowcount or 0

    async def save_episode(
        self,
        session_id: str,
        episode_id: Optional[str] = None,
        event_data: Optional[Any] = None,
        summary: Optional[str] = None,
    ) -> int:
        """保存情景事件"""
        if episode_id is None:
            episode_id = str(uuid4())

        episode = EpisodicEvent(
            session_id=session_id,
            episode_id=episode_id,
            event_data=event_data if isinstance(event_data, dict) else {"event": event_data},
            summary=summary,
        )
        self._session.add(episode)
        await self._session.flush()
        return episode.id

    async def get_episode(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取单个情景事件"""
        result = await self._session.execute(
            select(EpisodicEvent).where(EpisodicEvent.episode_id == episode_id)
        )
        episode = result.scalar_one_or_none()
        if episode:
            return {
                "id": episode.episode_id,
                "event": episode.event_data,
                "summary": episode.summary,
                "created_at": episode.created_at,
            }
        return None

    async def get_recent_episodes(
        self,
        session_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """获取最近的 N 个情景事件"""
        result = await self._session.execute(
            select(EpisodicEvent)
            .where(EpisodicEvent.session_id == session_id)
            .order_by(EpisodicEvent.created_at.desc())
            .limit(limit)
        )
        episodes = result.scalars().all()
        return [
            {
                "id": e.episode_id,
                "event": e.event_data,
                "summary": e.summary,
                "created_at": e.created_at,
            }
            for e in reversed(episodes)
        ]

    async def clear_episodes(self, session_id: str) -> int:
        """清空会话的所有情景事件"""
        result = await self._session.execute(
            delete(EpisodicEvent).where(EpisodicEvent.session_id == session_id)
        )
        return result.rowcount or 0

    async def save_working(
        self,
        session_id: str,
        memory_key: str,
        memory_value: Any,
    ) -> int:
        """保存或更新工作记忆"""
        stmt = insert(WorkingMemory).values(
            session_id=session_id,
            memory_key=memory_key,
            memory_value=memory_value
            if isinstance(memory_value, dict)
            else {"value": memory_value},
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["session_id", "memory_key"],
            set_={
                "memory_value": stmt.excluded.memory_value,
                "deleted_at": None,
            },
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        logger.info(f"[PostgresSaver] 保存工作记忆: session={session_id}, key={memory_key}")
        return result.inserted_primary_key[0] if result.inserted_primary_key else 0

    async def get_working(
        self,
        session_id: str,
        memory_key: str,
    ) -> Optional[Dict[str, Any]]:
        """获取单个工作记忆"""
        result = await self._session.execute(
            select(WorkingMemory).where(
                WorkingMemory.session_id == session_id,
                WorkingMemory.memory_key == memory_key,
                WorkingMemory.deleted_at.is_(None),
            )
        )
        memory = result.scalar_one_or_none()
        if memory:
            return {"key": memory.memory_key, "value": memory.memory_value}
        return None

    async def get_all_working(self, session_id: str) -> Dict[str, Any]:
        """获取会话的所有工作记忆"""
        result = await self._session.execute(
            select(WorkingMemory).where(
                WorkingMemory.session_id == session_id,
                WorkingMemory.deleted_at.is_(None),
            )
        )
        memories = result.scalars().all()
        return {m.memory_key: m.memory_value for m in memories}

    async def delete_working(self, session_id: str, memory_key: str) -> bool:
        """软删除工作记忆"""
        result = await self._session.execute(
            update(WorkingMemory)
            .where(
                WorkingMemory.session_id == session_id,
                WorkingMemory.memory_key == memory_key,
            )
            .values(deleted_at=None)
        )
        return (result.rowcount or 0) > 0

    async def clear_working(self, session_id: str) -> int:
        """清空会话的所有工作记忆"""
        result = await self._session.execute(
            update(WorkingMemory)
            .where(
                WorkingMemory.session_id == session_id,
                WorkingMemory.deleted_at.is_(None),
            )
            .values(deleted_at=None)
        )
        return result.rowcount or 0

    async def save_session_context(
        self,
        session_id: str,
        context_data: Dict[str, Any],
    ) -> None:
        """批量保存会话上下文（消息、事实、事件、工作记忆）"""
        if "messages" in context_data:
            for msg in context_data["messages"]:
                await self.save_message(
                    session_id=session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    metadata=msg.get("metadata"),
                )

        if "facts" in context_data:
            for key, value in context_data["facts"].items():
                await self.save_fact(session_id=session_id, fact_key=key, fact_value=value)

        if "episodes" in context_data:
            for episode in context_data["episodes"]:
                await self.save_episode(
                    session_id=session_id,
                    episode_id=episode.get("id"),
                    event_data=episode.get("event"),
                    summary=episode.get("summary"),
                )

        if "working" in context_data:
            for key, value in context_data["working"].items():
                await self.save_working(
                    session_id=session_id, memory_key=key, memory_value=value
                )

        await self._session.commit()

    async def load_session_context(self, session_id: str) -> Dict[str, Any]:
        """加载会话完整上下文"""
        messages = await self.get_messages(session_id)
        facts = await self.get_all_facts(session_id)
        episodes = await self.get_recent_episodes(session_id, limit=100)
        working = await self.get_all_working(session_id)

        return {
            "messages": messages,
            "facts": facts,
            "episodes": episodes,
            "working": working,
        }
