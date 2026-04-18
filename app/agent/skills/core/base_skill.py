"""Skill 基类

基于 SKILL.md 格式重构的基类，支持渐进式披露架构。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseSkill(ABC):
    """Skill 基类"""

    # 默认参数定义（可被子类覆盖）
    DEFAULT_PARAMETERS: List[Dict[str, Any]] = []

    def __init__(self):
        self.name: str = self.__class__.__name__
        self.description: str = ""
        self.parameters: List[Dict[str, Any]] = self.DEFAULT_PARAMETERS
        self._skill_dir: Optional[Path] = None

    def set_skill_dir(self, path: Path):
        """设置 Skill 目录路径"""
        self._skill_dir = path

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """执行 Skill（异步）"""
        pass

    def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证参数

        Returns:
            (是否有效, 错误信息)
        """
        required = [p for p in self.parameters if p.get("required", False)]
        for req in required:
            param_name = req.get("name")
            if param_name not in params or params[param_name] is None:
                return False, f"缺少必需参数: {param_name}"
        return True, None

    def get_schema(self) -> Dict[str, Any]:
        """获取 Skill 的 JSON Schema"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def get_json_schema(self) -> Dict[str, Any]:
        """获取 JSON Schema 格式的参数定义"""
        properties = {}
        required = []

        for param in self.parameters:
            name = param.get("name")
            p = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if "enum" in param:
                p["enum"] = param["enum"]
            if "default" in param:
                p["default"] = param["default"]
            properties[name] = p

            if param.get("required", False):
                required.append(name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    @classmethod
    def from_metadata(cls, metadata: Dict[str, Any]) -> "BaseSkill":
        """从元数据创建 Skill 实例"""
        skill = cls()
        if "name" in metadata:
            skill.name = metadata["name"]
        if "description" in metadata:
            skill.description = metadata["description"]
        if "parameters" in metadata:
            # 从 JSON Schema properties 转换
            params = metadata["parameters"]
            if isinstance(params, dict) and "properties" in params:
                skill.parameters = []
                for name, spec in params["properties"].items():
                    p = {
                        "name": name,
                        "type": spec.get("type", "string"),
                        "description": spec.get("description", ""),
                    }
                    if name in params.get("required", []):
                        p["required"] = True
                    if "enum" in spec:
                        p["enum"] = spec["enum"]
                    if "default" in spec:
                        p["default"] = spec["default"]
                    skill.parameters.append(p)
            elif isinstance(params, list):
                skill.parameters = params
        return skill
