"""Search Files Skill - 任务目录内代码搜索（先搜后读，替代整读/列目录漫游）"""

import os
import re
import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.skills.core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OUTPUT_CHARS = 50_000
MAX_FILE_BYTES = 1024 * 1024   # 单文件超过 1MB 跳过
MAX_FILES_SCANNED = 5000       # 最多扫描文件数
MAX_LINE_LEN = 300             # 匹配行截断长度
TEXT_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".java", ".c", ".cpp",
    ".h", ".hpp", ".go", ".rs", ".rb", ".php", ".sh", ".css", ".scss",
    ".html", ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt",
    ".sql", ".xml", ".cfg", ".env", ".rst", ".log",
}


def _get_tasks_dir() -> Path:
    from app.agent.skills.file_operations.skill import get_tasks_dir
    return get_tasks_dir()


class SearchFilesSkill(BaseSkill):
    """任务目录内代码搜索 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "pattern", "type": "string", "required": True,
         "description": "正则（target=content）或文件名 glob（target=files，如 *.py）"},
        {"name": "target", "type": "string", "required": False, "default": "content",
         "description": "content=搜内容；files=按文件名找文件"},
        {"name": "path", "type": "string", "required": False, "default": ".",
         "description": "搜索起始目录（相对任务目录）"},
        {"name": "file_glob", "type": "string", "required": False,
         "description": "只搜匹配的文件名（如 *.py），可选"},
        {"name": "output_mode", "type": "string", "required": False, "default": "content",
         "description": "content / files_only / count（仅 target=content 时）"},
        {"name": "limit", "type": "number", "required": False, "default": 50,
         "description": "最大返回条数（默认 50，上限 200）"},
        {"name": "offset", "type": "number", "required": False, "default": 0,
         "description": "跳过前 N 条（翻页）"},
    ]

    def __init__(self):
        super().__init__()
        self.name = "search_files"
        self.description = "任务目录内搜索代码内容/文件名（关键词定位，先搜后读）"
        self.parameters = self.DEFAULT_PARAMETERS

    # ---------- 路径解析与安全（与 file_operations read 同规则） ----------

    def _resolve_base(self, path: str, project_root: Optional[str]) -> Optional[Path]:
        """解析搜索起始目录；必须落在任务目录内，否则返回 None"""
        try:
            tasks_dir = _get_tasks_dir()
            p = Path(path or ".")
            if p.is_absolute():
                resolved = p.resolve()
            elif project_root:
                resolved = (tasks_dir / project_root / p).resolve()
            else:
                resolved = (tasks_dir / p).resolve()
            if resolved.is_relative_to(tasks_dir):
                return resolved
            logger.warning("[SearchFiles] 路径越界，拒绝: %s", resolved)
            return None
        except Exception as e:
            logger.warning("[SearchFiles] 路径解析失败: %s", e)
            return None

    @staticmethod
    def _skip_dir(name: str) -> bool:
        return name.startswith(".") or name in {"__pycache__", "node_modules", ".git"}

    def _collect_files(self, base: Path, file_glob: Optional[str]):
        """收集待搜文件（跳过隐藏/缓存目录、二进制、超大文件）
        返回 ([(relpath, Path), ...], overflow: bool)"""
        result = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not self._skip_dir(d)]
            for fname in sorted(files):
                if self._skip_dir(fname):
                    continue
                if file_glob and not fnmatch.fnmatch(fname, file_glob):
                    continue
                fp = Path(root, fname)
                try:
                    if fp.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if len(result) >= MAX_FILES_SCANNED:
                    return result, True
                try:
                    rel = str(fp.relative_to(base))
                except ValueError:
                    rel = str(fp)
                result.append((rel, fp))
        return result, False

    # ---------- 主入口 ----------

    async def execute(self, **kwargs) -> SkillResult:
        pattern = str(kwargs.get("pattern") or "").strip()
        # 模型常用 mode/type 传目标（生产实测 mode:"filename"、type:"content"）——别名归一到 target
        target = str(kwargs.get("target") or kwargs.get("mode") or kwargs.get("type") or "content").lower()
        if target in ("filename", "filenames", "filename_search", "file", "files"):
            target = "files"
        elif target in ("text", "grep", "content"):
            target = "content"
        start_path = str(kwargs.get("path") or ".")
        file_glob = str(kwargs.get("file_glob") or "").strip() or None
        output_mode = str(kwargs.get("output_mode") or "content").lower()
        task_path = kwargs.get("task_path")
        session_id = kwargs.get("session_id")

        # 未提供 pattern = 想看目录里有什么 → 按文件名全列
        # （生产实测"缺少 pattern 参数"反复报错，且 planner 因工具失败跳过观察，白烧轮次）
        _no_pattern = not pattern
        if _no_pattern:
            pattern = "*"
            target = "files"

        try:
            limit = min(max(1, int(kwargs.get("limit", DEFAULT_LIMIT))), MAX_LIMIT)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        try:
            offset = max(0, int(kwargs.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0

        # 会话项目目录（与 file_operations 相同的解析优先级）
        project_root = task_path
        if not project_root and session_id:
            try:
                from app.agent.skills.file_operations.skill import get_allowed_project_root
                project_root = await get_allowed_project_root(session_id) or None
            except Exception:
                project_root = None

        base = self._resolve_base(start_path, project_root)
        if base is None:
            return SkillResult(success=False,
                               error=f"安全检查失败：禁止搜索路径 {start_path}（须在任务目录内）")
        if not base.exists():
            return SkillResult(success=False, error=f"目录不存在: {start_path}")
        if not base.is_dir():
            return SkillResult(success=False, error=f"路径是文件不是目录: {start_path}")

        try:
            if target == "files":
                res = self._search_files(base, pattern, offset, limit)
            else:
                res = self._search_content(base, pattern, file_glob, output_mode, offset, limit)
            if _no_pattern and res.success:
                _n = res.data.get("note") or ""
                res.data["note"] = (_n + "；" if _n else "") + "未提供 pattern，已列出该目录下的文件"
            return res
        except re.error as e:
            # pattern 不是正则但像文件名 glob（生产实测模型传 *.py / * 当 pattern）
            # → 降级按文件名搜，返回结果+说明，别硬报错浪费一轮
            if any(ch in pattern for ch in "*?["):
                try:
                    fallback = self._search_files(base, pattern, offset, limit)
                    if fallback.success:
                        note = fallback.data.get("note") or ""
                        fallback.data["note"] = (note + "；" if note else "") + \
                            f"pattern 不是合法正则（{e}），已按文件名 glob 匹配"
                        return fallback
                except Exception:
                    pass
            return SkillResult(success=False,
                               error=f"pattern 不是合法正则: {e}（用 Python 正则，"
                                     f"如 delete|remove、def \\w+\\(、class .*Model；"
                                     f"按文件名找文件请传 target=files）")
        except Exception as e:
            logger.error("[SearchFiles] 搜索失败: %s", e)
            return SkillResult(success=False, error=str(e))

    # ---------- target=files：按文件名 glob ----------

    def _search_files(self, base: Path, pattern: str, offset: int, limit: int) -> SkillResult:
        files, overflow = self._collect_files(base, None)
        hits: List[str] = []
        total = 0
        for rel, fp in files:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(fp.name, pattern):
                total += 1
                if total > offset and len(hits) < limit:
                    hits.append(rel)
        note = ""
        if total > offset + len(hits):
            note = f"还有更多结果，用 offset={offset + len(hits)} 翻页"
        if overflow:
            note = (note + "；" if note else "") + f"文件数超过 {MAX_FILES_SCANNED}，已截断，请缩小 path"
        return SkillResult(
            success=True,
            data={"matches": hits, "total_matches": total, "files_hit": total,
                  "has_more": bool(note), "note": note},
            metadata={"operation": "search_files", "target": "files"},
        )

    # ---------- target=content：正则搜内容 ----------

    def _search_content(self, base: Path, pattern: str, file_glob: Optional[str],
                        output_mode: str, offset: int, limit: int) -> SkillResult:
        rx = re.compile(pattern)
        files, overflow = self._collect_files(base, file_glob)
        per_file: Dict[str, int] = {}
        detail: List[str] = []
        total = 0
        files_hit = 0

        for rel, fp in files:
            # 文本判定：扩展名白名单 + 首块无 NUL
            if fp.suffix.lower() not in TEXT_EXTS:
                try:
                    head = fp.open("rb").read(2048)
                except OSError:
                    continue
                if b"\x00" in head:
                    continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            file_count = 0
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not rx.search(line):
                    continue
                file_count += 1
                total += 1
                if output_mode == "content" and total > offset and len(detail) < limit:
                    snippet = line.strip()[:MAX_LINE_LEN]
                    detail.append(f"{rel}:{lineno}: {snippet}")
            if file_count:
                files_hit += 1
                per_file[rel] = file_count

        if output_mode == "count":
            top = sorted(per_file.items(), key=lambda kv: -kv[1])[:limit]
            matches = [f"{p}: {c}" for p, c in top]
        elif output_mode == "files_only":
            matches = sorted(per_file.keys())[offset:offset + limit]
        else:
            matches = detail

        note = ""
        if total > offset + len(matches) and output_mode == "content":
            note = f"还有更多匹配，用 offset={offset + len(matches)} 翻页"
        elif not total:
            note = "0 命中：换关键词（同义词/更宽的正则）或检查 path/file_glob"
        if overflow:
            note = (note + "；" if note else "") + f"文件数超过 {MAX_FILES_SCANNED}，已截断，请缩小 path"

        data = {
            "matches": matches,
            "total_matches": total,
            "files_hit": files_hit,
            "has_more": bool(note and total > offset + len(matches)),
            "note": note,
        }
        out_len = sum(len(m) for m in matches)
        if out_len > MAX_OUTPUT_CHARS:
            data["matches"] = matches[: max(1, limit // 2)]
            data["note"] = (data["note"] + "；" if data["note"] else "") + \
                "结果过长已截断，用 output_mode=count 探分布或加 file_glob 缩窄"
        return SkillResult(
            success=True,
            data=data,
            metadata={"operation": "search_files", "target": "content",
                      "output_mode": output_mode},
        )


# 导出 Skill 实例
skill = SearchFilesSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
