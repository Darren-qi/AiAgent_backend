"""Skill 基类"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from dataclasses import dataclass


@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class BaseSkill(ABC):
    """Skill 基类"""

    def __init__(self):
        self.name = self.__class__.__name__
        self.description = ""
        self.parameters: List[Dict[str, Any]] = []

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """执行 Skill"""
        pass

    def validate_parameters(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        return True

    def get_schema(self) -> Dict[str, Any]:
        """获取 Skill 的 JSON Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
