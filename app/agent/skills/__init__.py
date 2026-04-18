"""Skill 系统模块

支持两种结构：
1. 新结构（渐进式）：skills/<name>/SKILL.md + skill.py
2. 旧结构（兼容）：skills/builtin/*.py（暂时保留）
"""

from app.agent.skills.core.base_skill import BaseSkill, SkillResult
from app.agent.skills.core.progressive_loader import (
    ProgressiveSkillLoader,
    SkillMetadata,
    get_loader,
    bootstrap,
)

__all__ = [
    # 新核心
    "BaseSkill",
    "SkillResult",
    "ProgressiveSkillLoader",
    "SkillMetadata",
    "get_loader",
    "bootstrap",
]
