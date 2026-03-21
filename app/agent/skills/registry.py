"""Skill 注册器"""

from typing import Dict, Type, Optional, List, Any
from app.agent.skills.base import BaseSkill, SkillResult


class SkillRegistry:
    """Skill 注册器 - 管理所有可用 Skill"""

    _instance: Optional["SkillRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._skills: Dict[str, BaseSkill] = {}
        self._skill_classes: Dict[str, Type[BaseSkill]] = {}
        self._initialized = True

    def register(self, skill: BaseSkill) -> None:
        """注册 Skill"""
        self._skills[skill.name] = skill
        self._skill_classes[skill.name] = type(skill)

    def register_class(self, skill_class: Type[BaseSkill]) -> None:
        """注册 Skill 类"""
        skill = skill_class()
        self.register(skill)

    def get(self, name: str) -> Optional[BaseSkill]:
        """获取 Skill"""
        return self._skills.get(name)

    def get_all(self) -> Dict[str, BaseSkill]:
        """获取所有 Skill"""
        return self._skills.copy()

    def get_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 的 Schema"""
        return [skill.get_schema() for skill in self._skills.values()]

    def list_names(self) -> List[str]:
        """列出所有 Skill 名称"""
        return list(self._skills.keys())


registry = SkillRegistry()
