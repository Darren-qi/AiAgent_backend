"""
Redis 缓存模块

提供 Redis 缓存功能，支持：
- 简单的键值缓存
- 缓存过期时间
- 缓存模式（可选）
"""

import json
from typing import Any, Optional

import redis.asyncio as redis
from redis.asyncio import Redis

from app.core.config import get_settings


class CacheManager:
    """
    缓存管理器

    提供异步 Redis 缓存操作。
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.settings = get_settings()
        self.redis_url = redis_url or self.settings.redis_url
        self._client: Optional[Redis] = None

    async def connect(self) -> None:
        """建立 Redis 连接"""
        if self._client is None:
            self._client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

    async def disconnect(self) -> None:
        """关闭 Redis 连接"""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def client(self) -> Redis:
        """获取 Redis 客户端（确保已连接）"""
        if self._client is None:
            raise RuntimeError("Redis 未连接，请先调用 connect()")
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值（已反序列化），不存在则返回 None
        """
        value = await self.client.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def set(
        self,
        key: str,
        value: Any,
        expire: Optional[int] = None,
    ) -> bool:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值（必须是可序列化的）
            expire: 过期时间（秒），None 表示永不过期

        Returns:
            是否设置成功
        """
        # 序列化值
        if not isinstance(value, str):
            serialized = json.dumps(value)
        else:
            serialized = value

        result = await self.client.set(key, serialized, ex=expire)
        return bool(result)

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        result = await self.client.delete(key)
        return bool(result)

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return await self.client.exists(key) > 0

    async def expire(self, key: str, seconds: int) -> bool:
        """设置键的过期时间"""
        return await self.client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """获取键的剩余生存时间（秒）"""
        return await self.client.ttl(key)

    async def increment(self, key: str, amount: int = 1) -> int:
        """递增计数器"""
        return await self.client.incr(key, amount)

    async def decrement(self, key: str, amount: int = 1) -> int:
        """递减计数器"""
        return await self.client.decr(key, amount)

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """批量获取缓存值"""
        if not keys:
            return {}

        values = await self.client.mget(keys)
        result = {}
        for key, value in zip(keys, values):
            if value is not None:
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value
        return result

    async def set_many(
        self,
        mapping: dict[str, Any],
        expire: Optional[int] = None,
    ) -> None:
        """批量设置缓存"""
        if not mapping:
            return

        pipeline = self.client.pipeline()
        for key, value in mapping.items():
            if not isinstance(value, str):
                value = json.dumps(value)
            pipeline.set(key, value, ex=expire)
        await pipeline.execute()

    async def clear_pattern(self, pattern: str) -> int:
        """
        清除匹配模式的所有键

        Args:
            pattern: 键模式，如 "user:*" 或 "cache:session:*"

        Returns:
            删除的键数量
        """
        count = 0
        async for key in self.client.scan_iter(match=pattern):
            await self.client.delete(key)
            count += 1
        return count

    # =========================================
    # 便捷方法
    # =========================================

    async def cache_result(
        self,
        key: str,
        func,
        expire: Optional[int] = None,
        *args,
        **kwargs,
    ):
        """
        缓存函数结果

        如果缓存存在，直接返回缓存值。
        否则调用函数，结果存入缓存后返回。

        Args:
            key: 缓存键
            func: 要调用的函数
            expire: 过期时间
            *args, **kwargs: 函数参数

        Returns:
            函数结果（可能是缓存值）
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        result = await func(*args, **kwargs)
        await self.set(key, result, expire=expire)
        return result


# 全局缓存管理器实例
cache_manager = CacheManager()


# =============================================
# 便捷函数
# =============================================

async def get_cache(key: str) -> Optional[Any]:
    """获取缓存值"""
    return await cache_manager.get(key)


async def set_cache(key: str, value: Any, expire: Optional[int] = None) -> bool:
    """设置缓存值"""
    return await cache_manager.set(key, value, expire)


async def delete_cache(key: str) -> bool:
    """删除缓存"""
    return await cache_manager.delete(key)
