"""长期记忆模块"""

from typing import Dict, Any, Optional, List

from app.agent.memory.base import BaseMemory


class SemanticMemory(BaseMemory):
    """语义记忆 - 存储结构性知识"""

    def __init__(self):
        self._facts: Dict[str, Any] = {}

    async def add(self, key: str, value: Any) -> None:
        """添加事实"""
        self._facts[key] = value

    async def get(self, key: str) -> Optional[Any]:
        """获取事实"""
        return self._facts.get(key)

    async def remove(self, key: str) -> None:
        """删除事实"""
        if key in self._facts:
            del self._facts[key]

    async def clear(self) -> None:
        """清空事实"""
        self._facts = {}

    async def get_all(self) -> Dict[str, Any]:
        """获取所有事实"""
        return self._facts.copy()

    async def search(self, query: str) -> List[Dict[str, Any]]:
        """搜索相关事实"""
        results = []
        query_lower = query.lower()

        for key, value in self._facts.items():
            if query_lower in key.lower() or query_lower in str(value).lower():
                results.append({"key": key, "value": value})

        return results


class EpisodicMemory(BaseMemory):
    """情景记忆 - 存储经历和事件"""

    def __init__(self, max_episodes: int = 100):
        self.max_episodes = max_episodes
        self._episodes: List[Dict[str, Any]] = []

    async def add(self, key: str, value: Any) -> None:
        """添加事件"""
        episode = {
            "id": key,
            "event": value,
        }

        self._episodes.append(episode)

        if len(self._episodes) > self.max_episodes:
            self._episodes.pop(0)

    async def get(self, key: str) -> Optional[Any]:
        """获取事件"""
        for episode in self._episodes:
            if episode["id"] == key:
                return episode["event"]
        return None

    async def remove(self, key: str) -> None:
        """删除事件"""
        self._episodes = [e for e in self._episodes if e["id"] != key]

    async def clear(self) -> None:
        """清空事件"""
        self._episodes = []

    async def get_all(self) -> Dict[str, Any]:
        """获取所有事件"""
        return {e["id"]: e["event"] for e in self._episodes}

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的事件"""
        return self._episodes[-limit:]


class LongTermMemory:
    """长期记忆"""

    def __init__(self, max_episodes: int = 100):
        self.semantic = SemanticMemory()
        self.episodic = EpisodicMemory(max_episodes=max_episodes)

    async def add_fact(self, key: str, value: Any) -> None:
        """添加事实"""
        await self.semantic.add(key, value)

    async def get_fact(self, key: str) -> Optional[Any]:
        """获取事实"""
        return await self.semantic.get(key)

    async def search_facts(self, query: str) -> List[Dict[str, Any]]:
        """搜索事实"""
        return await self.semantic.search(query)

    async def add_episode(self, key: str, event: Any) -> None:
        """添加事件"""
        await self.episodic.add(key, event)

    async def get_episode(self, key: str) -> Optional[Any]:
        """获取事件"""
        return await self.episodic.get(key)

    def get_recent_episodes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近事件"""
        return self.episodic.get_recent(limit)
