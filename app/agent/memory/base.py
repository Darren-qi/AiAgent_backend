"""记忆基类"""

from abc import ABC, abstractmethod
from typing import Any


class BaseMemory(ABC):
    """记忆基类"""

    @abstractmethod
    async def add(self, key: str, value: Any) -> None:
        """添加记忆"""
        pass

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """获取记忆"""
        pass

    @abstractmethod
    async def remove(self, key: str) -> None:
        """删除记忆"""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """清空记忆"""
        pass

    @abstractmethod
    async def get_all(self) -> dict[str, Any]:
        """获取所有记忆"""
        pass
