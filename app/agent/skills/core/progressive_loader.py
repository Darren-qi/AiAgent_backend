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

# 阶段二：Harness 元数据合法枚举（非法值在 _parse_frontmatter 拒绝）
VALID_RISKS = ("read", "write", "exec", "network")
VALID_STAGES = ("plan", "execute", "both")


@dataclass
class SkillMetadata:
    """Skill 元数据（轻量，快速加载）"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "system"
    tags: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    operation_targets: Dict[str, List[str]] = field(default_factory=dict)  # 操作→目标参数契约
    usage: str = ""  # 出错 JIT 注入的调用须知（渐进第三级）
    # === 阶段二（2026-11-16）：对齐 AutoGen ToolMeta 的 Harness 元数据 ===
    risk: str = ""  # read/write/exec/network（空=未声明，bootstrap 打 warning）
    path_arg: str = ""  # 主路径参数名（如 path），供阶段三 safe_path 收口
    url_arg: str = ""  # URL 参数名（如 url），供阶段三 safe_url
    timeout: int = 0  # 执行超时秒数，0=用全局默认
    retry: int = 0  # 瞬态重试次数（幂等 read/list 类才 >=1），0=不重试
    stage: str = "both"  # plan/execute/both：阶段四 stage 白名单消费
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
            "operation_targets": self.operation_targets,
            "usage": self.usage,
            "risk": self.risk,
            "path_arg": self.path_arg,
            "url_arg": self.url_arg,
            "timeout": self.timeout,
            "retry": self.retry,
            "stage": self.stage,
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

        # === 阶段二校验：非法枚举硬拒绝（raise → bootstrap 跳过该技能）===
        risk = str(data.get("risk") or "").strip().lower()
        if risk and risk not in VALID_RISKS:
            raise ValueError(
                f"非法 risk={risk!r}（合法: {VALID_RISKS}）: {skill_md}")
        stage = str(data.get("stage") or "").strip().lower() or "both"
        if stage not in VALID_STAGES:
            raise ValueError(
                f"非法 stage={stage!r}（合法: {VALID_STAGES}）: {skill_md}")

        try:
            timeout = int(data.get("timeout") or 0)
            retry = int(data.get("retry") or 0)
        except (TypeError, ValueError) as e:
            raise ValueError(f"timeout/retry 必须是整数: {skill_md}") from e

        operation_targets = data.get("operation_targets") or {}
        # 缺失软约束：先 warning 不拦（阶段二约定，测试断言 9/9 硬覆盖）
        if not risk:
            logger.warning(
                "[ProgressiveLoader] %s 缺少 risk 声明（Harness 元数据不完整）",
                skill_md)
        if not operation_targets:
            logger.warning(
                "[ProgressiveLoader] %s 缺少 operation_targets 契约"
                "（执行前无法做结构校验）", skill_md)

        return SkillMetadata(
            name=data.get("name", skill_dir.name),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", "system"),
            tags=data.get("tags", []),
            parameters=data.get("parameters", {}),
            operation_targets=operation_targets,
            usage=data.get("usage") or "",
            risk=risk,
            path_arg=str(data.get("path_arg") or ""),
            url_arg=str(data.get("url_arg") or ""),
            timeout=max(timeout, 0),
            retry=max(retry, 0),
            stage=stage,
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

    # === 阶段二：注册中心查询 API（阶段三 RunGuard / 阶段四白名单消费）===

    def get_by_stage(self, stage: str) -> List[SkillMetadata]:
        """按阶段取技能：stage=plan 返回规划期可用集（both + plan）。"""
        return [
            m for m in self._index.values()
            if m.stage == stage or m.stage == "both"
        ]

    def get_by_risk(self, risk: str) -> List[SkillMetadata]:
        """按风险分级取技能（read/write/exec/network）。"""
        return [m for m in self._index.values() if m.risk == risk]

    def get_guard_meta(self, name: str) -> Optional[Dict[str, Any]]:
        """RunGuard 消费的元数据切片（未注册返回 None → UNKNOWN_SKILL）。"""
        m = self._index.get(name)
        if not m:
            return None
        return {
            "name": m.name,
            "risk": m.risk,
            "path_arg": m.path_arg,
            "url_arg": m.url_arg,
            "timeout": m.timeout,
            "retry": m.retry,
            "stage": m.stage,
            "operation_targets": m.operation_targets,
            "parameters": m.parameters,
        }

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
        from app.agent.skills.guard import tool_guard

        # 阶段三：RunGuard 单检查点（替换原 validate_params_structure L5 闸门；
        # 语义不变——不通过不进 skill）。顺序：白名单→契约/类型→路径/URL 约束
        # →连续失败熔断→风险门。拒绝返回结构化 code 走 correction。
        deny = tool_guard.begin(name, params)
        if deny:
            logger.warning(
                "[ProgressiveLoader] 守卫拒绝 skill=%s code=%s: %s",
                name, deny["error_code"], deny["message"])
            return SkillResult(
                success=False,
                error=deny["message"],
                error_code=deny["error_code"],
            )

        def _done(result: "SkillResult") -> "SkillResult":
            """统一出口：补 error_code + guard.finish（熔断计数/审计）。"""
            result = _stamp_error_code(result)
            tool_guard.finish(
                name, ok=result.success, detail=result.error,
                error_code=result.error_code)
            return result

        # 优先使用注册的 executor
        if name in self._executors:
            try:
                executor = self._executors[name]
                result = await executor(**params)
                return _done(result)
            except asyncio.CancelledError:
                raise  # 传播取消信号（超时/取消不计失败，由外层决定）
            except Exception as e:
                logger.error(f"[ProgressiveLoader] 执行 {name} 失败: {e}")
                return _done(SkillResult(
                    success=False, error=str(e), error_code="EXEC_FAILED"))

        # 动态导入模块
        module = self._load_module(name)
        if not module:
            return _done(SkillResult(
                success=False,
                error=f"Skill '{name}' 未找到",
                error_code="UNKNOWN_SKILL",
            ))

        # 调用 execute 方法
        try:
            if hasattr(module, 'execute'):
                return _done(await module.execute(**params))
            else:
                return _done(SkillResult(
                    success=False,
                    error=f"Skill '{name}' 没有 execute 方法",
                    error_code="EXEC_FAILED",
                ))
        except asyncio.CancelledError:
            raise  # 传播取消信号（超时/取消不计失败，由外层决定）
        except Exception as e:
            logger.error(f"[ProgressiveLoader] 执行 {name} 出错: {e}")
            return _done(SkillResult(
                success=False, error=str(e), error_code="EXEC_FAILED"))

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


def validate_params_structure(name: str, params: Any) -> Optional[str]:
    """参数结构崩坏防线（TC-S16-04，2026-11-14 生产取证）。

    现场：模型把大文件内容内联进参数 JSON，输出结构崩坏——解析出的
    params 键变成代码碎片、缺该操作的目标参数，执行必报"缺少 path 参数"
    连环失败。按 skill frontmatter 声明的 ``operation_targets`` 契约校验
    （契约写在 skill 文档里，代码不逐 skill 硬编码）；未声明契约的
    skill 一律不拦，避免误伤。

    Returns:
        问题描述（放行时返回 None）
    """
    if not isinstance(params, dict):
        return f"params 不是 JSON 对象（收到 {type(params).__name__}）"
    if not params:
        return None
    try:
        meta = get_loader().get_metadata(name)
    except Exception:  # noqa: BLE001 - 索引不可用时不阻塞执行
        return None
    if not meta or not meta.operation_targets:
        return None
    op = str(params.get("operation") or "").strip().lower()
    # 阶段二：契约支持 "*" 通配（无 operation 参数的技能用它声明必有参数键）
    if op and op in meta.operation_targets:
        wanted = meta.operation_targets[op] or []
    elif "*" in meta.operation_targets:
        wanted = meta.operation_targets["*"] or []
        op = op or "*"
    else:
        return None
    if wanted and not any(k in params for k in wanted):
        return (
            f"operation={op} 缺少目标参数（{name} 需要 "
            f"{'/'.join(wanted)} 之一），实际参数键为 "
            f"{sorted(str(k) for k in params)[:8]}"
            "——参数结构疑似崩坏，禁止执行"
        )
    return None


def classify_params_problem(prob: str) -> str:
    """validate_params_structure 的问题描述 → error_code（阶段一协议）。

    只分类已知形态；结构问题默认按缺参处理（MISSING_PARAM 是
    生产最高频形态，TC-S16-04）。
    """
    if "不是 JSON 对象" in (prob or ""):
        return "INVALID_TYPE"
    return "MISSING_PARAM"


def classify_tool_error(error: Optional[str]) -> Optional[str]:
    """skill 返回的 error 文案 → error_code（缺参报错统一改写）。

    只改写能高置信分类的形态；其余保持 None 走字符串兜底，
    避免 EXEC_FAILED 顶掉"文件不存在"等更具体的修正策略。
    """
    if not error:
        return None
    if "缺少" in error and "参数" in error:
        return "MISSING_PARAM"
    if "未找到" in error:
        return "UNKNOWN_SKILL"
    return None


def _stamp_error_code(result: "SkillResult") -> "SkillResult":
    """给失败的 SkillResult 补 error_code（已有 code 不覆盖）。"""
    if not result.success and result.error_code is None:
        result.error_code = classify_tool_error(result.error)
    return result


# 全局加载器实例
_global_loader: Optional[ProgressiveSkillLoader] = None


def get_loader() -> ProgressiveSkillLoader:
    """获取全局渐进式加载器"""
    global _global_loader
    if _global_loader is None:
        _global_loader = ProgressiveSkillLoader()
        # 启动时引导（类 docstring 设计的第 1 步）。修复：此前全仓无人调用
        # bootstrap → _index 恒空 → planner 的"## 可用工具"段恒为空白、
        # JIT schema hint 也拿不到参数（2026-11-11 发现）
        try:
            _global_loader.bootstrap()
        except Exception as e:  # noqa: BLE001 - 引导失败降级为空清单，不阻塞
            logger.warning("[ProgressiveLoader] bootstrap 失败（技能清单降级为空）: %s", e)
    return _global_loader


def bootstrap() -> int:
    """引导全局加载器"""
    loader = get_loader()
    return loader.bootstrap()
