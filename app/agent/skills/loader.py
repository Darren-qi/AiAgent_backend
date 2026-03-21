"""
Skill 加载器模块

支持从内置目录和外部目录动态加载 Skill。
"""

import os
import sys
import importlib
import inspect
import logging
from pathlib import Path
from typing import Dict, List, Type, Optional, Any, Set
from app.agent.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    Skill 动态加载器

    支持从指定目录动态加载 Skill 类。
    功能：
    - 从内置目录加载
    - 从外部目录加载（experience/skills）
    - 热加载（检测文件变化）
    - Skill 验证
    """

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = base_path or self._get_default_path()
        self._loaded_skills: Dict[str, Type[BaseSkill]] = {}
        self._skill_instances: Dict[str, BaseSkill] = {}
        self._loaded_paths: Set[str] = set()

    def _get_default_path(self) -> str:
        """获取默认 Skill 路径"""
        return os.path.join(
            os.path.dirname(__file__),
            "builtin"
        )

    def load_from_directory(self, directory: str) -> Dict[str, BaseSkill]:
        """
        从目录加载所有 Skill

        Args:
            directory: Skill 目录路径

        Returns:
            加载的 Skill 实例字典
        """
        loaded = {}
        path = Path(directory)

        if not path.exists():
            logger.warning(f"[SkillLoader] 目录不存在: {directory}")
            return loaded

        logger.info(f"[SkillLoader] 从目录加载 Skill: {directory}")
        self._loaded_paths.add(str(path.absolute()))

        for file_path in path.rglob("*.py"):
            if file_path.name.startswith("_"):
                continue

            module_name = self._path_to_module(file_path)
            try:
                skills = self._load_skills_from_module(module_name)
                for name, skill in skills.items():
                    loaded[name] = skill
                    self._loaded_skills[name] = type(skill)
                    self._skill_instances[name] = skill
                    logger.debug(f"[SkillLoader] 加载 Skill: {name}")
            except Exception as e:
                logger.warning(f"[SkillLoader] 加载模块失败 {module_name}: {e}")

        logger.info(f"[SkillLoader] 从 {directory} 加载了 {len(loaded)} 个 Skill")
        return loaded

    def _load_skills_from_module(self, module_name: str) -> Dict[str, BaseSkill]:
        """从模块加载 Skill"""
        # 先尝试热加载：如果模块已加载，先移除
        if module_name in sys.modules:
            module = sys.modules[module_name]
            # 检查是否有新版本
            importlib.reload(module)
        else:
            module = importlib.import_module(module_name)

        return self._extract_skills_from_module(module)

    def load_from_external(self, external_path: str) -> Dict[str, BaseSkill]:
        """
        从外部路径加载 Skill（experience/skills/custom）

        Args:
            external_path: 外部 Skill 目录

        Returns:
            加载的 Skill 实例字典
        """
        return self.load_from_directory(external_path)

    def load_single(self, module_path: str, class_name: str) -> Optional[BaseSkill]:
        """
        加载单个 Skill

        Args:
            module_path: 模块路径 (如 app.agent.skills.builtin.code_generator)
            class_name: Skill 类名

        Returns:
            Skill 实例
        """
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            if issubclass(cls, BaseSkill):
                skill_instance = cls()
                self._skill_instances[skill_instance.name] = skill_instance
                return skill_instance
        except Exception as e:
            logger.error(f"[SkillLoader] 加载单个 Skill 失败: {e}")

        return None

    def _path_to_module(self, file_path: Path) -> str:
        """将文件路径转换为模块名"""
        parts = file_path.with_suffix("").parts
        if "app" in parts:
            idx = parts.index("app")
            parts = parts[idx:]
        return ".".join(parts)

    def _extract_skills_from_module(self, module) -> Dict[str, BaseSkill]:
        """从模块中提取所有 Skill 类"""
        skills = {}
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseSkill) and obj is not BaseSkill:
                # 跳过基类本身
                if obj.__name__ == "BaseSkill":
                    continue
                try:
                    skill_instance = obj()
                    skills[skill_instance.name] = skill_instance
                except Exception as e:
                    logger.warning(f"[SkillLoader] 实例化 Skill {obj.__name__} 失败: {e}")
        return skills

    def get_loaded_skills(self) -> Dict[str, Type[BaseSkill]]:
        """获取已加载的 Skill 类"""
        return self._loaded_skills.copy()

    def get_skill_instance(self, name: str) -> Optional[BaseSkill]:
        """获取 Skill 实例"""
        return self._skill_instances.get(name)

    def get_all_instances(self) -> Dict[str, BaseSkill]:
        """获取所有 Skill 实例"""
        return self._skill_instances.copy()

    def reload(self, skill_name: str) -> bool:
        """
        热加载单个 Skill

        Args:
            skill_name: Skill 名称

        Returns:
            是否成功
        """
        # 找到 Skill 所在的模块
        for path in self._loaded_paths:
            for file_path in Path(path).rglob("*.py"):
                if file_path.stem in skill_name.lower():
                    module_name = self._path_to_module(file_path)
                    try:
                        skills = self._load_skills_from_module(module_name)
                        if skill_name in skills:
                            self._skill_instances[skill_name] = skills[skill_name]
                            logger.info(f"[SkillLoader] 热加载 Skill: {skill_name}")
                            return True
                    except Exception as e:
                        logger.error(f"[SkillLoader] 热加载失败: {e}")
        return False

    def get_skill_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 的 Schema"""
        schemas = []
        for skill in self._skill_instances.values():
            schemas.append(skill.get_schema())
        return schemas


# 全局加载器实例
_global_loader: Optional[SkillLoader] = None


def get_global_loader() -> SkillLoader:
    """获取全局加载器实例"""
    global _global_loader
    if _global_loader is None:
        _global_loader = SkillLoader()
    return _global_loader


def load_builtin_skills() -> Dict[str, BaseSkill]:
    """
    加载所有内置 Skill

    Returns:
        Skill 名称到实例的字典
    """
    loader = SkillLoader()
    builtin_path = os.path.join(
        os.path.dirname(__file__),
        "builtin"
    )
    return loader.load_from_directory(builtin_path)


def load_external_skills(external_path: Optional[str] = None) -> Dict[str, BaseSkill]:
    """
    从外部路径加载 Skill

    Args:
        external_path: 外部 Skill 目录，默认从 experience/skills 加载

    Returns:
        加载的 Skill 实例字典
    """
    if external_path is None:
        # 尝试从 experience/skills 加载
        project_root = Path(__file__).parent.parent.parent.parent
        external_path = str(project_root / "experience" / "skills" / "custom")

    loader = get_global_loader()
    return loader.load_from_external(external_path)
