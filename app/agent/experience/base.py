"""
经验基类模块
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Experience:
    """经验条目"""
    id: str
    task: str
    task_type: str
    description: str
    solution: str
    steps: List[Dict[str, Any]]
    success: bool
    created_at: datetime
    success_count: int = 1
    metadata: Optional[Dict[str, Any]] = None


class BaseExperienceStore(ABC):
    """经验存储基类"""

    @abstractmethod
    async def save(self, experience: Experience) -> str:
        """保存经验"""
        pass

    @abstractmethod
    async def get(self, exp_id: str) -> Optional[Experience]:
        """获取经验"""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        task_type: Optional[str] = None,
        top_k: int = 5
    ) -> List[Experience]:
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
