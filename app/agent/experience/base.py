"""
经验基类模块
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Experience:
    """经验条目"""
    id: str
    task: str
    task_type: str
    description: str
    solution: str
    steps: list[dict[str, Any]]
    success: bool
    created_at: datetime
    success_count: int = 1
    metadata: dict[str, Any] | None = None


class BaseExperienceStore(ABC):
    """经验存储基类"""

    @abstractmethod
    async def save(self, experience: Experience) -> str:
        """保存经验"""
        pass

    @abstractmethod
    async def get(self, exp_id: str) -> Experience | None:
        """获取经验"""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        task_type: str | None = None,
        top_k: int = 5
    ) -> list[Experience]:
        """搜索经验"""
        pass

    @abstractmethod
    async def delete(self, exp_id: str) -> bool:
        """删除经验"""
        pass

    @abstractmethod
    async def increment_success(self, exp_id: str) -> None:
        """增加成功次数"""
        pass
