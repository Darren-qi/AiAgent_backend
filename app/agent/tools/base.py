"""
工具基类模块
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from dataclasses import dataclass


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseTool(ABC):
    """工具基类"""

    def __init__(self):
        self.name = self.__class__.__name__
        self.description = ""
        self.parameters: List[Dict[str, Any]] = []
        self.enabled = True

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    def get_schema(self) -> Dict[str, Any]:
        """获取工具的 JSON Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
        }

    async def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证参数"""
        required = [p["name"] for p in self.parameters if p.get("required", False)]
        for name in required:
            if name not in params:
                return False, f"缺少必需参数: {name}"
        return True, None


class ToolMetadata:
    """工具元数据"""

    def __init__(
        self,
        name: str,
        description: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        version: str = "1.0.0",
    ):
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags or []
        self.version = version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
        }
