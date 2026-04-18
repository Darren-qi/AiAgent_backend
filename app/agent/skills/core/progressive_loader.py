"""
渐进式 Skill 加载器

核心特性：
1. 分层加载：启动时仅加载索引（YAML frontmatter），按需加载完整内容
2. 动态执行：Skill 执行时才导入实际模块
3. 热重载：支持在不重启服务的情况下更新 Skill
"""

import asyncio
import os
import re
import sys
import yaml
import logging
import importlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SkillMetadata:
    """Skill 元数据（轻量，快速加载）"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "system"
    tags: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    file_path: Path = field(default=None)
    skill_dir: Path = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "parameters": self.parameters,
        }

    def matches_query(self, query: str) -> float:
        """
        计算与查询的匹配度分数

        Args:
            query: 用户意图描述

        Returns:
            0.0 - 1.0 的匹配度分数
        """
        query_lower = query.lower()
        desc_lower = self.description.lower()
        score = 0.0

        # 1. 描述精确匹配
        if query_lower in desc_lower:
            score += 0.5

        # 2. 查询词在描述中（部分匹配）
        query_chars = list(query_lower.replace(' ', ''))
        matched_chars = sum(1 for c in query_chars if c in desc_lower)
        if matched_chars >= len(query_chars) * 0.6:
            score += 0.3

        # 3. 标签匹配
        for tag in self.tags:
            if tag.lower() in query_lower or query_lower in tag.lower():
                score += 0.2

        # 4. 名称匹配
        name_clean = self.name.lower().replace("_", "-").replace(" ", "")
        query_clean = query_lower.replace("_", "-").replace(" ", "")
        if name_clean in query_clean or query_clean in name_clean:
            score += 0.3
        else:
            for part in name_clean.split("-"):
                if len(part) >= 3 and part in query_clean:
                    score += 0.1

        # 5. 关键词匹配（中英文通用）
        keywords = self._extract_keywords(self.description)
        query_keywords = self._extract_keywords(query)
        overlap = len(set(keywords) & set(query_keywords))
        if overlap > 0:
            score += min(overlap * 0.15, 0.3)

        return min(score, 1.0)

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """从文本中提取关键词"""
        # 移除停用词，提取有意义的词
        stopwords = {"的", "是", "在", "和", "了", "用", "于", "或", "及", "可", "能", "支", "持", "当", "用", "时"}
        words = re.findall(r'[\w]+', text.lower())
        return [w for w in words if len(w) > 1 and w not in stopwords]


@dataclass
class SkillInfo:
    """Skill 完整信息"""
    metadata: SkillMetadata
    full_content: str = ""  # 完整 SKILL.md 内容
    skill_module: Optional[Any] = None  # 执行时加载


class ProgressiveSkillLoader:
    """
    渐进式 Skill 加载器

    加载流程：
    1. bootstrap() - 启动时：仅解析 YAML frontmatter，构建轻量索引
    2. match() - 匹配时：基于描述筛选候选 Skill
    3. get_full_content() - 按需加载：读取完整 SKILL.md
    4. execute() - 执行时：动态导入 skill.py 并调用
    """

    def __init__(
        self,
        skills_root: Optional[Path] = None,
        external_root: Optional[Path] = None
    ):
        """
        Args:
            skills_root: 内置 Skill 根目录
            external_root: 外部 Skill 根目录（experience/skills）
        """
        self.skills_root = skills_root or self._get_default_skills_root()
        self.external_root = external_root

        # 索引数据（启动时加载）
        self._index: Dict[str, SkillMetadata] = {}

        # 完整内容缓存（按需加载）
        self._content_cache: Dict[str, str] = {}

        # 模块缓存（执行时加载）
        self._module_cache: Dict[str, Any] = {}

        # Skill 执行器工厂
        self._executors: Dict[str, Callable] = {}

        # 是否已初始化
        self._bootstrapped = False

    def _get_default_skills_root(self) -> Path:
        """获取默认 Skill 根目录"""
        # progressive_loader.py 在 core/ 目录下
        # parent = skills/, 不需要再 / "skills"
        return Path(__file__).parent.parent

    def bootstrap(self) -> int:
        """
        启动时引导：快速扫描并构建索引

        Returns:
            加载的 Skill 数量
        """
        if self._bootstrapped:
            logger.warning("[ProgressiveLoader] 已初始化，跳过")
            return len(self._index)

        logger.info("[ProgressiveLoader] 开始引导...")

        # 扫描内置 Skill
        count = self._scan_directory(self.skills_root, is_external=False)

        # 扫描外部 Skill
        if self.external_root and self.external_root.exists():
            count += self._scan_directory(self.external_root, is_external=True)

        self._bootstrapped = True
        logger.info(f"[ProgressiveLoader] 引导完成，加载 {count} 个 Skill")
        return count

    def _scan_directory(self, root: Path, is_external: bool) -> int:
        """
        扫描目录中的所有 Skill

        Args:
            root: 目录路径
            is_external: 是否为外部 Skill

        Returns:
            扫描到的 Skill 数量
        """
        count = 0
        if not root.exists():
            return count

        for skill_dir in root.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                metadata = self._parse_frontmatter(skill_md, skill_dir, is_external)
                self._index[metadata.name] = metadata
                count += 1
                logger.debug(f"[ProgressiveLoader] 索引: {metadata.name}")
            except Exception as e:
                logger.warning(f"[ProgressiveLoader] 解析 {skill_md} 失败: {e}")

        return count

    def _parse_frontmatter(
        self,
        skill_md: Path,
        skill_dir: Path,
        is_external: bool
    ) -> SkillMetadata:
        """
        解析 SKILL.md 的 YAML frontmatter

        Args:
            skill_md: SKILL.md 文件路径
            skill_dir: Skill 目录路径
            is_external: 是否为外部 Skill

        Returns:
            SkillMetadata 对象
        """
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取 YAML frontmatter
        frontmatter_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not frontmatter_match:
            raise ValueError(f"缺少 YAML frontmatter: {skill_md}")

        yaml_str = frontmatter_match.group(1)

        # 简单 YAML 解析（支持基本类型）
        data = self._parse_yaml(yaml_str)

        return SkillMetadata(
            name=data.get("name", skill_dir.name),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", "system"),
            tags=data.get("tags", []),
            parameters=data.get("parameters", {}),
            file_path=skill_md,
            skill_dir=skill_dir,
        )

    def _parse_yaml(self, yaml_str: str) -> Dict[str, Any]:
        """解析 YAML 字符串"""
        try:
            return yaml.safe_load(yaml_str) or {}
        except yaml.YAMLError as e:
            logger.warning(f"[ProgressiveLoader] YAML 解析错误: {e}")
            return {}

    def match(self, query: str, top_k: int = 5) -> List[SkillMetadata]:
        """
        基于用户意图匹配候选 Skill

        Args:
            query: 用户意图描述
            top_k: 返回前 k 个最匹配的 Skill

        Returns:
            按匹配度排序的 Skill 列表
        """
        scores = []
        for name, metadata in self._index.items():
            score = metadata.matches_query(query)
            if score > 0:
                scores.append((score, metadata))

        # 按分数降序排序
        scores.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scores[:top_k]]

    def match_by_tags(self, tags: List[str]) -> List[SkillMetadata]:
        """
        基于标签匹配 Skill

        Args:
            tags: 标签列表

        Returns:
            匹配的 Skill 列表
        """
        results = []
        for metadata in self._index.values():
            if any(tag in metadata.tags for tag in tags):
                results.append(metadata)
        return results

    def get_metadata(self, name: str) -> Optional[SkillMetadata]:
        """获取 Skill 元数据"""
        return self._index.get(name)

    def get_all_metadata(self) -> List[SkillMetadata]:
        """获取所有 Skill 元数据"""
        return list(self._index.values())

    def get_full_content(self, name: str) -> Optional[str]:
        """
        获取完整 SKILL.md 内容（按需加载）

        Args:
            name: Skill 名称

        Returns:
            完整 Markdown 内容
        """
        if name in self._content_cache:
            return self._content_cache[name]

        metadata = self._index.get(name)
        if not metadata or not metadata.file_path:
            return None

        try:
            with open(metadata.file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._content_cache[name] = content
            return content
        except Exception as e:
            logger.error(f"[ProgressiveLoader] 读取 {name} 内容失败: {e}")
            return None

    def get_skill_info(self, name: str) -> Optional[SkillInfo]:
        """
        获取 Skill 完整信息

        Args:
            name: Skill 名称

        Returns:
            SkillInfo 对象
        """
        metadata = self._index.get(name)
        if not metadata:
            return None

        return SkillInfo(
            metadata=metadata,
            full_content=self.get_full_content(name) or "",
        )

    def register_executor(self, name: str, executor: Callable):
        """
        注册 Skill 执行器

        Args:
            name: Skill 名称
            executor: 执行器函数/类
        """
        self._executors[name] = executor

    async def execute(self, name: str, params: Dict[str, Any]) -> "SkillResult":
        """
        执行 Skill（动态加载模块）

        Args:
            name: Skill 名称
            params: 执行参数

        Returns:
            SkillResult 对象
        """
        from app.agent.skills.core.base_skill import SkillResult

        # 优先使用注册的 executor
        if name in self._executors:
            try:
                executor = self._executors[name]
                result = await executor(**params)
                return result
            except asyncio.CancelledError:
                raise  # 传播取消信号
            except Exception as e:
                logger.error(f"[ProgressiveLoader] 执行 {name} 失败: {e}")
                return SkillResult(success=False, error=str(e))

        # 动态导入模块
        module = self._load_module(name)
        if not module:
            return SkillResult(success=False, error=f"Skill '{name}' 未找到")

        # 调用 execute 方法
        try:
            if hasattr(module, 'execute'):
                return await module.execute(**params)
            else:
                return SkillResult(success=False, error=f"Skill '{name}' 没有 execute 方法")
        except asyncio.CancelledError:
            raise  # 传播取消信号
        except Exception as e:
            logger.error(f"[ProgressiveLoader] 执行 {name} 出错: {e}")
            return SkillResult(success=False, error=str(e))

    def _load_module(self, name: str) -> Optional[Any]:
        """
        动态加载 Skill 模块

        Args:
            name: Skill 名称

        Returns:
            加载的模块
        """
        if name in self._module_cache:
            return self._module_cache[name]

        metadata = self._index.get(name)
        if not metadata or not metadata.skill_dir:
            return None

        # 尝试导入 skill.py
        skill_file = metadata.skill_dir / "skill.py"
        if not skill_file.exists():
            logger.warning(f"[ProgressiveLoader] {name} 没有 skill.py")
            return None

        # 构建模块名
        parts = metadata.skill_dir.parts
        if "app" in parts:
            idx = parts.index("app")
            module_parts = parts[idx:]
            # 替换 skills 为 skills.<name>
            for i, p in enumerate(module_parts):
                if p == "skills":
                    module_parts = list(module_parts[:i+1]) + [name, "skill"]
                    break
            module_name = ".".join(module_parts)
        else:
            module_name = f"{metadata.skill_dir.name}.skill"

        try:
            module = importlib.import_module(module_name)
            self._module_cache[name] = module
            return module
        except Exception as e:
            logger.error(f"[ProgressiveLoader] 导入 {name} 模块失败: {e}")
            return None

    def reload(self, name: str) -> bool:
        """
        热重载单个 Skill

        Args:
            name: Skill 名称

        Returns:
            是否成功
        """
        # 清除缓存
        if name in self._content_cache:
            del self._content_cache[name]
        if name in self._module_cache:
            module = self._module_cache[name]
            if module.__name__ in sys.modules:
                importlib.reload(module)

        # 重新解析元数据
        metadata = self._index.get(name)
        if metadata and metadata.file_path and metadata.file_path.exists():
            try:
                new_metadata = self._parse_frontmatter(
                    metadata.file_path,
                    metadata.skill_dir,
                    False
                )
                self._index[name] = new_metadata
                logger.info(f"[ProgressiveLoader] 热重载: {name}")
                return True
            except Exception as e:
                logger.error(f"[ProgressiveLoader] 热重载 {name} 失败: {e}")

        return False

    def get_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 的 Schema（用于 LLM 规划）"""
        return [m.to_dict() for m in self._index.values()]

    def get_skill_list_str(self) -> str:
        """
        获取 Skill 列表字符串（用于 prompt）

        格式：
        skill_name: 描述 [tags]
        """
        lines = []
        for metadata in self._index.values():
            tags_str = f" [{','.join(metadata.tags)}]" if metadata.tags else ""
            lines.append(f"- {metadata.name}: {metadata.description}{tags_str}")
        return "\n".join(lines)


# 全局加载器实例
_global_loader: Optional[ProgressiveSkillLoader] = None


def get_loader() -> ProgressiveSkillLoader:
    """获取全局渐进式加载器"""
    global _global_loader
    if _global_loader is None:
        _global_loader = ProgressiveSkillLoader()
    return _global_loader


def bootstrap() -> int:
    """引导全局加载器"""
    loader = get_loader()
    return loader.bootstrap()
