"""Skill 系统模块"""

from app.agent.skills.base import BaseSkill, SkillResult
from app.agent.skills.registry import SkillRegistry, registry
from app.agent.skills.loader import SkillLoader, load_builtin_skills

# 加载内置 Skill
_builtin_skills = load_builtin_skills()
for name, skill in _builtin_skills.items():
    registry.register(skill)

__all__ = [
    "BaseSkill",
    "SkillResult",
    "SkillRegistry",
    "SkillLoader",
    "registry",
    "load_builtin_skills",
]
