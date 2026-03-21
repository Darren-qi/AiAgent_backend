"""记忆基类"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseMemory(ABC):
    """记忆基类"""

    @abstractmethod
    async def add(self, key: str, value: Any) -> None:
        """添加记忆"""
        pass

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
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
    async def get_all(self) -> Dict[str, Any]:
        """获取所有记忆"""
        pass
