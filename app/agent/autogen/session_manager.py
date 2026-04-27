# -*- coding: utf-8 -*-
"""
会话管理器：多用户会话隔离
每个 session_id 对应一个独立的 AgentTeam 实例
"""

import asyncio
import logging
from typing import Dict, Optional, Callable, Any

from app.agent.autogen.team.group_chat import AgentTeam

logger = logging.getLogger(__name__)


class SessionManager:
    """多用户会话管理器（单例）"""

    _instance: Optional["SessionManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: Dict[str, AgentTeam] = {}
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    async def get_or_create_team(
        self,
        session_id: str,
        on_event: Optional[Callable] = None,
        db_session=None,
    ) -> AgentTeam:
        """获取或创建 session 对应的 AgentTeam"""
        async with self._lock:
            if session_id not in self._sessions:
                logger.info(f"[SessionManager] 创建新团队: {session_id}")
                team = AgentTeam(
                    session_id=session_id,
                    on_message=on_event,
                    db_session=db_session,
                )
                self._sessions[session_id] = team
            else:
                # 更新回调（每次执行可能不同）
                self._sessions[session_id]._on_message = on_event
            return self._sessions[session_id]

    async def execute(
        self,
        session_id: str,
        task: str,
        context: Dict[str, Any],
        on_event: Callable,
        db_session=None,
    ) -> Dict[str, Any]:
        """执行任务"""
        team = await self.get_or_create_team(session_id, on_event=on_event, db_session=db_session)
        # 如果有新任务，添加到历史记录（支持同一会话中多次对话）
        if task:
            team._history.append({"role": "user", "content": task})
        return await team.run(task=task, context=context)

    async def abort(self, session_id: str) -> bool:
        """中止任务"""
        if session_id in self._sessions:
            team = self._sessions[session_id]
            await team.abort()
            return True
        return False

    def remove_session(self, session_id: str):
        """移除会话"""
        self._sessions.pop(session_id, None)
        logger.info(f"[SessionManager] 移除会话: {session_id}")


# 全局单例
session_manager = SessionManager()
