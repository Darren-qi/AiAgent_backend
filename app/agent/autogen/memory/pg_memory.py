# -*- coding: utf-8 -*-
"""AutoGen 记忆层 - 基于现有 PostgresSaver 的短期/长期记忆管理"""

from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.memory.pgsaver import PostgresSaver


class PGMemory:
    """
    AutoGen 团队记忆管理器

    短期记忆：当前会话对话历史（存 conversation_messages 表）
    长期记忆：跨会话事实摘要（存 semantic_facts 表）
    压缩阈值：消息数超过 COMPRESS_THRESHOLD 时触发摘要压缩
    """

    COMPRESS_THRESHOLD = 20  # 超过此数量触发压缩
    KEEP_RECENT = 6          # 压缩后保留最近 N 条原始消息

    def __init__(self, session_id: str, db: AsyncSession):
        self.session_id = session_id
        self._saver = PostgresSaver(db)
        self._messages: List[Dict[str, Any]] = []  # 内存缓存
        self._loaded = False

    async def load(self) -> None:
        """从 DB 加载历史消息到内存缓存"""
        if self._loaded:
            return
        msgs = await self._saver.get_recent_messages(self.session_id, limit=50)
        self._messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
        self._loaded = True

    async def add(self, role: str, content: str, agent_name: str = "") -> None:
        """添加一条消息，超阈值时自动压缩"""
        meta = {"agent": agent_name} if agent_name else {}
        await self._saver.save_message(self.session_id, role, content, meta)
        self._messages.append({"role": role, "content": content, "agent": agent_name})

        if len(self._messages) >= self.COMPRESS_THRESHOLD:
            await self._compress()

    async def _compress(self) -> None:
        """将旧消息压缩为摘要，写入长期记忆，保留最近 KEEP_RECENT 条"""
        old = self._messages[: -self.KEEP_RECENT]
        recent = self._messages[-self.KEEP_RECENT :]

        summary_lines = []
        for m in old:
            agent = m.get("agent", m["role"])
            summary_lines.append(f"[{agent}]: {m['content'][:200]}")
        summary = "【历史摘要】\n" + "\n".join(summary_lines)

        # 摘要写入长期记忆（semantic_facts）
        import time
        key = f"summary_{int(time.time())}"
        await self._saver.save_fact(self.session_id, key, {"summary": summary})

        # 内存只保留摘要占位 + 最近消息
        self._messages = [{"role": "system", "content": summary, "agent": "compressor"}] + recent

    async def get_context(self, max_messages: int = 20) -> List[Dict[str, str]]:
        """返回给 LLM 的上下文（只含 role/content）"""
        msgs = self._messages[-max_messages:]
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    async def get_long_term_summary(self) -> str:
        """获取所有历史摘要，用于新会话注入"""
        facts = await self._saver.get_all_facts(self.session_id)
        summaries = [v["summary"] for k, v in facts.items() if k.startswith("summary_") and "summary" in v]
        return "\n\n".join(summaries) if summaries else ""

    async def save_artifact_fact(self, stage: str, file_path: str) -> None:
        """记录阶段产物路径到长期记忆"""
        await self._saver.save_fact(self.session_id, f"artifact_{stage}", {"path": file_path})
