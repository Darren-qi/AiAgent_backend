"""
工具基类模块
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


class BaseTool(ABC):
    """工具基类"""

    def __init__(self):
        self.name = self.__class__.__name__
        self.description = ""
        self.parameters: list[dict[str, Any]] = []
        self.enabled = True

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    def get_schema(self) -> dict[str, Any]:
        """获取工具的 JSON Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
        }

    async def validate_params(self, params: dict[str, Any]) -> tuple[bool, str | None]:
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
        tags: list[str] | None = None,
        version: str = "1.0.0",
    ):
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags or []
        self.version = version

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "version": self.version,
        }
