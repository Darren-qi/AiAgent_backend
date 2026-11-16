"""File Operations Skill - 文件操作技能"""

import os
import asyncio
import json
import re
import time
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from app.agent.skills.core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


def _salvage_files_array(text: str):
    """从被截断的 JSON 文本抢救 "files": [ ... ] 里**完整**的对象元素。

    字符串感知的括号扫描（转义/引号内括号不算数，不靠正则数括号）：
    最后一个没闭合的元素（max_tokens 截断点）直接丢弃，完整元素照常执行。
    2026-11-13 TC-S16-01：批量写 13.6KB 参数被截断，整批降级 raw 全废。
    """
    m = re.search(r'"files"\s*:\s*\[', text)
    if not m:
        return None
    items = []
    i = m.end()
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "]":
            break
        if text[i] != "{":
            break
        depth, in_str, esc, j, end = 0, False, False, i, -1
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end < 0:
            break  # 元素没闭合（截断点）→ 丢弃
        try:
            obj = json.loads(text[i:end + 1])
            if isinstance(obj, dict):
                items.append(obj)
        except Exception:
            pass
        i = end + 1
    return items or None


def get_project_root() -> Path:
    """
    获取项目根目录（AiAgent 目录）
    使用更可靠的方式获取
    """
    # 方法1: 从环境变量获取
    project_root = os.environ.get("PROJECT_ROOT")
    if project_root:
        return Path(project_root).resolve()

    # 方法2: 从模块路径推断
    # __file__ = AiAgent/backend/app/agent/skills/file_operations/skill.py
    # 4个parent: skill.py -> file_operations -> skills -> agent -> app
    # 再2个parent: backend -> AiAgent
    module_path = Path(__file__).resolve()
    app_dir = module_path.parent.parent.parent.parent  # .../AiAgent_backend_langgraph/app
    # 上两级：app -> AiAgent_backend_langgraph -> AiAgent（tasks 与前后端目录同级）
    return app_dir.parent.parent


def get_tasks_dir() -> Path:
    """
    获取 tasks 目录路径
    确保返回的路径在项目根目录之外

    优先级：
    1. TASKS_DIR 环境变量（最高优先级，与 Django 项目保持一致）
    2. LOCAL_STORAGE_PATH 环境变量
    3. {项目根目录}/tasks（默认）
    """
    # 优先级1: TASKS_DIR 环境变量
    tasks_dir = os.environ.get("TASKS_DIR")
    if tasks_dir:
        return Path(tasks_dir).resolve()

    # 优先级2: LOCAL_STORAGE_PATH 环境变量
    storage_path = os.environ.get("LOCAL_STORAGE_PATH")
    if storage_path:
        if os.path.isabs(storage_path):
            return Path(storage_path).resolve()
        # 相对路径相对于项目根目录
        return (get_project_root() / storage_path).resolve()

    # 优先级3: 默认使用项目根目录下的 tasks 文件夹
    default_tasks = get_project_root() / "tasks"
    default_tasks.mkdir(parents=True, exist_ok=True)
    return default_tasks.resolve()


# ============ 会话限制验证函数 ============

async def get_allowed_project_root(session_id: str) -> str:
    """
    获取会话允许的项目根目录
    从 SessionContext 表读取 task_path
    """
    if not session_id:
        return ''

    try:
        from app.agent.tools.session_context import get_session_context
        task_path = await get_session_context(session_id, "task_path")
        return task_path or ''
    except Exception as e:
        logger.debug(f"[FileOps] get_allowed_project_root error: {e}")
        return ''


async def set_allowed_project_root(session_id: str, project_root: str):
    """
    设置会话允许的项目根目录
    每次创建新项目时都更新为最新的项目名称
    同时记录文件信息
    """
    if not session_id or not project_root:
        logger.debug(f"[FileOps] set_allowed_project_root: session_id={session_id}, project_root={project_root}")
        return

    try:
        from app.agent.tools.session_context import set_session_context
        await set_session_context(session_id, "task_path", project_root)
        logger.info(f"[FileOps] 更新 task_path: {session_id} -> {project_root}")
    except Exception as e:
        logger.debug(f"[FileOps] set_allowed_project_root error: {e}")


def _parse_files_param(files):
    """解析 files 批量参数 → [{"path","content"},...]；非法返回 SkillResult 错误。

    write/read 批量共用（2026-11-13 并发批量创建/读取）。
    """
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except Exception:
            return SkillResult(success=False,
                               error='files 必须是 JSON 数组: [{"path": "a.py", "content": "..."}]')
    if not isinstance(files, list) or not files:
        return SkillResult(success=False,
                           error='files 必须是非空数组: [{"path": "a.py", "content": "..."}]')
    parsed = []
    for i, f in enumerate(files):
        if isinstance(f, str):
            f = {"path": f}
        if not isinstance(f, dict) or not str(f.get("path") or "").strip():
            return SkillResult(success=False, error=f"files[{i}] 缺少 path 字段")
        parsed.append({"path": str(f["path"]).strip(), "content": f.get("content") or ""})
    return parsed


class FileOperationsSkill(BaseSkill):
    """文件操作 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "operation", "type": "string", "required": True, "description": "操作类型，可选值: write(全量写文件), edit(局部替换修改已有文件，优先), create(创建项目目录), read(读文件), list(列目录), delete(删除文件), move(移动/归类：path=源, dest=目标，移动后原位置不再有该文件). 注意: 不要使用 create_directory/create_file/mkdir 等无效值！"},
        {"name": "path", "type": "string", "required": True, "description": "文件路径"},
        {"name": "dest", "type": "string", "required": False, "description": "move 操作的目标路径（相对任务目录，如 backend/app.py，也可为目录）"},
        {"name": "content", "type": "string", "required": False, "description": "写入内容（write/create操作时需要）"},
        {"name": "old_text", "type": "string", "required": False, "description": "待替换的原文片段（edit 用）：必须与文件内容逐字一致（含空格/缩进/换行），且在文件中唯一"},
        {"name": "new_text", "type": "string", "required": False, "description": "替换后的新文本（edit 用）"},
        {"name": "replace_all", "type": "boolean", "required": False, "description": "old_text 命中多处时是否全部替换（edit 用，默认 false=只允许唯一命中）", "default": False},
        {"name": "encoding", "type": "string", "required": False, "description": "文件编码", "default": "utf-8"},
        {"name": "offset", "type": "number", "required": False, "description": "读取起始行号（read 用，默认 1）", "default": 1},
        {"name": "limit", "type": "number", "required": False, "description": "读取行数（read 用，默认 200，最大 500）", "default": 200},
    ]

    def __init__(self):
        super().__init__()
        self.name = "file_operations"
        self.description = "文件读写、目录操作"
        self.parameters = self.DEFAULT_PARAMETERS
        # 获取 tasks 目录
        self._tasks_dir = get_tasks_dir()
        # 会话限制：允许的项目根目录（异步获取）
        self._allowed_project_root = None

    def _is_safe_path(self, file_path: str) -> bool:
        """检查路径是否安全 - 只允许在 tasks 目录下操作"""
        try:
            resolved = Path(file_path).resolve()
            # 必须在 tasks 目录下
            if resolved.is_relative_to(self._tasks_dir):
                return True
            return False
        except Exception:
            return False

    def _is_safe_read_path(self, file_path: str) -> bool:
        """检查读取路径是否安全 - 只允许在 tasks 目录下操作"""
        try:
            resolved = Path(file_path).resolve()
            # 必须在 tasks 目录下
            if resolved.is_relative_to(self._tasks_dir):
                return True
            return False
        except Exception:
            return False

    _FILE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
        '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala', '.lua',
        '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd',
        '.html', '.htm', '.css', '.scss', '.sass', '.less',
        '.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.config', '.env',
        '.xml', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp',
        '.md', '.txt', '.rst', '.log', '.sql', '.db', '.sqlite',
        '.zip', '.tar', '.gz', '.rar', '.7z',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.ttf', '.otf', '.woff', '.woff2', '.eot',
        '.vue', '.svelte',
        'requirements.txt', 'package.json', 'Cargo.toml', 'go.mod', 'go.sum',
        'Makefile', 'CMakeLists.txt', 'setup.py', 'Pipfile', 'Pipfile.lock',
        'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
    }

    def _looks_like_file(self, name: str) -> bool:
        """判断是否像文件名（而非目录名）"""
        if not name:
            return False
        lower = name.lower()
        for ext in self._FILE_EXTENSIONS:
            if lower.endswith(ext):
                return True
        if '.' in name and not name.startswith('.'):
            return True
        return False

    def _looks_like_python_code(self, path: str) -> bool:
        """判断路径是否像Python代码（而非合法文件路径）"""
        if not path:
            return False
        # 检查是否包含Python关键字或语法
        python_indicators = [
            'def ', 'class ', 'import ', 'from ', 'return ',
            '@app.', '@route', 'if __name__', 'print(',
            '()', '->', ':', 'async def', 'await '
        ]
        for indicator in python_indicators:
            if indicator in path:
                return True
        return False

    # 操作别名映射：将 LLM 常见的误用操作名映射到正确操作
    _OPERATION_ALIASES = {
        # 创建项目
        "create_directory": "create",
        "create_dir": "create",
        "mkdir": "create",
        "init_project": "create",
        "create_project": "create",
        # 写入文件
        "write_file": "write",
        "file_write": "write",
        "create_file": "write",
        "new_file": "write",
        "add_file": "write",
        # 编辑文件（局部替换；2026-11-13 起不再静默映射到全量 write）
        "edit_file": "edit",
        "modify_file": "edit",
        "update_file": "edit",
        "patch": "edit",
        "edit": "edit",
        # 读取文件
        "read_file": "read",
        "file_read": "read",
        "view_file": "read",
        # 列出目录
        "list_dir": "list",
        "ls": "list",
        "list_directory": "list",
        # 删除
        "remove": "delete",
        "rm": "delete",
        "delete_file": "delete",
        "delete_dir": "delete",
        "delete": "delete",
        # 移动/归类（移动后原位置不再有该文件）
        "move": "move",
        "mv": "move",
        "rename": "move",
        "move_file": "move",
    }

    async def execute(self, **kwargs) -> SkillResult:
        # raw 降级恢复（2026-11-13 TC-S16-01 取证：单次批量写内容超长 → params
        # 被截断成不完整 JSON → 解析降级 {"raw": "..."} → 恒报"缺少 path"烧光
        # 轮次）。先整段 json.loads；失败则字符串感知扫描抢救 files[] 里
        # **完整**的元素先落盘，让模型下一轮补剩下的。
        if isinstance(kwargs.get("raw"), str):
            _raw_s = kwargs.pop("raw")
            _recovered: Optional[Dict[str, Any]] = None
            try:
                _recovered = json.loads(_raw_s)
            except Exception:
                _items = _salvage_files_array(_raw_s)
                if _items:
                    _recovered = {"files": _items}
                    _m = re.search(r'"operation"\s*:\s*"(\w+)"', _raw_s)
                    if _m:
                        _recovered["operation"] = _m.group(1)
            if isinstance(_recovered, dict) and _recovered:
                _recovered.update(kwargs)
                kwargs = _recovered
            # 恢复不了 → 保持原样走正常失败反馈，让模型修正参数
        operation = kwargs.get("operation", "").lower()
        file_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")
        task_path = kwargs.get("task_path")
        session_id = kwargs.get("session_id")

        # 初始化会话限制
        if session_id:
            self._allowed_project_root = await get_allowed_project_root(session_id)
            logger.debug(f"[FileOps] 会话 {session_id} 限制项目根目录: {self._allowed_project_root}")

        # —— 路径规范化（2026-11-13 用户反馈：查找没带/重复带任务目录 →
        # 获取不到文件）——模型常把任务目录名当相对路径前缀（task/app/x.py
        # 或 tasks/task/app/x.py），直接解析会拼成任务目录下一级的同名嵌套
        # （task/task/app/x.py）→ 文件不存在。统一剥掉前缀后再分发：
        # 顶层 path/dest/from/to/src + 批量 files[]/paths[] 元素都覆盖。
        # create/delete_task 的 path 语义特殊（可能就是任务名本身），不剥。
        _tp_norm = task_path if isinstance(task_path, str) else ""
        if _tp_norm and operation not in ("create", "delete_task"):
            kwargs = self._strip_task_prefix_kwargs(kwargs, _tp_norm)
            file_path = str(kwargs.get("path") or file_path)

        # 映射别名到有效操作
        if operation in self._OPERATION_ALIASES:
            operation = self._OPERATION_ALIASES[operation]

        # 操作名称映射（用于前端显示）
        operation_names = {
            "create": "init_project",
            "write": "write_file",
            "read": "read_file",
            "list": "list_dir",
            "delete": "delete_file",
            "edit": "edit_file",
            "move": "move_file",
        }
        friendly_action = operation_names.get(operation, "file_operations")

        # 批量并发读/写：files 数组（写=一次落盘多个互不依赖的文件；
        # 读=并行读多个）。2026-11-13 用户反馈骨架创建逐文件太慢；
        # 生产实测模型会自然把 files 推广到 read，read 必须同样收下，
        # 否则报"缺少 path 参数"浪费一轮。
        if kwargs.get("files") and operation in ("write", "read"):
            if operation == "read":
                result = await self._read_files_batch(
                    kwargs.get("files"), encoding, task_path, session_id)
            else:
                result = await self._write_files_batch(
                    kwargs.get("files"), encoding, task_path, session_id)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = ("write_file" if operation == "write"
                                            else "read_file")
            return result

        if operation == "write":
            if not file_path:
                return SkillResult(success=False, error="缺少 path 参数")
            result = await self._write_file(file_path, content, encoding, task_path, session_id)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "write_file"
            return result
        elif operation == "create":
            result = await self._create_project(file_path, content, encoding, task_path, session_id)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "init_project"
            return result
        elif operation == "read":
            if not file_path:
                return SkillResult(success=False, error="缺少 path 参数")
            result = await self._read_file(
                file_path, encoding, session_id, task_path,
                kwargs.get("offset", 1), kwargs.get("limit", 200),
            )
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "read_file"
            return result
        elif operation == "edit":
            # 批量局部替换：edits 数组（2026-11-13 用户测试：模型把 files
            # 的批量模式推广到 edit，发 edits:[{old,new}] → 报"缺少 old_text"
            # 白烧整轮预算）。每项 {path?, old/new 或 old_text/new_text,
            # replace_all?}，path 缺省用顶层 path；同文件多处按顺序应用。
            if kwargs.get("edits"):
                result = await self._edit_files_batch(
                    kwargs.get("edits"), file_path, encoding, session_id, task_path,
                )
                result.metadata = result.metadata or {}
                result.metadata["friendly_action"] = friendly_action
                result.metadata["operation"] = "edit_file"
                return result
            # files 批量（2026-11-14 TC-S16-03 生产取证：模型把 write/read/
            # delete/move 的 files 批量自然推广到 edit，发
            # files:[{path,old_string,new_string}] → 恒报"缺少 path 参数"
            # 连烧2轮）。files 语义=逐文件，每项必须带 path；替换键与 edits 同构。
            _files_param = kwargs.get("files")
            if isinstance(_files_param, list) and _files_param:
                result = await self._edit_files_batch(
                    _files_param, file_path, encoding, session_id, task_path,
                )
                result.metadata = result.metadata or {}
                result.metadata["friendly_action"] = friendly_action
                result.metadata["operation"] = "edit_file"
                return result
            if not file_path:
                return SkillResult(
                    success=False,
                    error="缺少 path 参数（单条: path+old_text/new_text; "
                          "批量: files=[{path,old_string,new_string}] "
                          "或 edits=[{old,new}]）")
            result = await self._edit_file(
                file_path,
                kwargs.get("old_text") if kwargs.get("old_text") is not None
                else kwargs.get("old_string"),
                kwargs.get("new_text") if kwargs.get("new_text") is not None
                else kwargs.get("new_string"),
                kwargs.get("replace_all", False), encoding, session_id, task_path,
            )
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "edit_file"
            return result
        elif operation == "list":
            result = await self._list_directory(file_path, task_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "list_dir"
            return result
        elif operation == "delete":
            # 批量删除：files=[{path}] 或 paths=["a","b"]（2026-11-13 TC-S16-01
            # 取证：模型把批量推广到 delete，files/paths 两种猜法各报一次
            # "缺少 path 参数"，清理轮次被烧掉）
            batch = kwargs.get("files") or kwargs.get("paths")
            if isinstance(batch, list) and batch:
                return await self._delete_files_batch(
                    batch, task_path, session_id, friendly_action)
            if not file_path:
                return SkillResult(success=False, error="缺少 path 参数")
            result = await self._delete_file(file_path, task_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "delete_file"
            return result
        elif operation == "move":
            # 批量移动：files 数组一次搬多个（2026-11-13 生产取证：模型自然把
            # 批量模式推广到 move，7 次报"缺少 path"全靠逐个补，烧掉轮次）
            files_param = kwargs.get("files")
            if isinstance(files_param, list) and files_param:
                return await self._move_files_batch(files_param, task_path)
            dest = (kwargs.get("dest") or kwargs.get("destination") or kwargs.get("dest_path")
                    or kwargs.get("target_path") or kwargs.get("to"))
            if not file_path:
                return SkillResult(success=False, error="move 操作缺少 path 参数（源路径）")
            if not dest:
                # 文案必须含"缺少/参数"→ 触发 planner 的全量参数 schema 注入
                return SkillResult(success=False,
                                   error="move 操作缺少 dest 参数（目标路径，"
                                         "如 dest=backend/app.py；destination 也可以）")
            result = await self._move_file(file_path, dest, task_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "move_file"
            return result
        else:
            valid_ops = ", ".join(sorted(set(self._OPERATION_ALIASES.values())))
            return SkillResult(
                success=False,
                error=f"不支持的操作: {operation}，有效操作: {valid_ops}",
                metadata={"operation": "file_operations", "friendly_action": "file_operations"}
            )

    async def _create_project(self, file_path: str, content: str, encoding: str, task_path: Optional[str] = None, session_id: Optional[str] = None) -> SkillResult:
        """
        创建项目结构（多文件批量创建）

        直接在 tasks 目录下创建 {project_name}_{timestamp} 文件夹
        不需要 task_时间戳 外层

        Args:
            file_path: 项目名称（带时间戳）
            content: 多文件内容，格式 "文件名:内容\n文件名:内容..."
                     如果为空，将创建基础 README.md 文件
            encoding: 文件编码
            task_path: 任务路径（如果有，提供项目名称）
            session_id: 会话ID（用于限制项目范围）

        Returns:
            SkillResult 包含 project_name（带时间戳）供后续 write 操作使用
        """
        try:
            # 1. 处理项目名称，生成带时间戳的文件夹名
            project_name = file_path.strip()

            # 如果是相对路径或绝对路径，提取文件夹名
            if '/' in project_name or '\\' in project_name:
                project_name = Path(project_name).name

            # 清理项目名称，保留合法字符
            import re as re_module
            safe_name = re_module.sub(r'[^\w\-]', '_', project_name)
            safe_name = re_module.sub(r'_+', '_', safe_name).strip('_-')
            if not safe_name:
                safe_name = "project"

            # 生成带时间戳的项目名
            timestamp = int(time.time())
            project_folder = f"{safe_name}_{timestamp}"

            # 目标目录：tasks/{project_name}_{timestamp}
            target_dir = self._tasks_dir / project_folder
            abs_target_dir = str(target_dir.resolve())

            # 2. 安全检查
            if not self._is_safe_path(abs_target_dir):
                return SkillResult(success=False, error=f"安全检查失败：禁止写入路径 {abs_target_dir}")

            # 3. 会话限制检查：如果是后续对话，只能在已允许的目录下操作
            if self._allowed_project_root:
                allowed_full_path = str((self._tasks_dir / self._allowed_project_root).resolve())
                if not abs_target_dir.startswith(allowed_full_path):
                    return SkillResult(
                        success=False,
                        error=f"错误：会话已限制项目范围为 '{self._allowed_project_root}' 目录下。您只能在该目录下创建文件或子目录，不能创建新的顶级项目。"
                    )

            # 4. 创建项目目录
            target_dir.mkdir(parents=True, exist_ok=True)
            created_files = []

            # 5. 如果没有提供内容，创建默认的 README.md
            if not content or not content.strip():
                content = f"README.md::\n# {safe_name}\n\nProject initialized at {timestamp}\n::END\n"

            # 6. 解析并创建文件
            # 格式支持：
            # (1) 单行格式：文件名::内容
            # (2) 多行格式：文件名::\n内容行1\n内容行2\n::END
            # 注意：旧格式（单冒号）仍然支持，但不适用于内容中包含冒号的情况
            if content:
                lines = content.split('\n')
                i = 0
                while i < len(lines):
                    line = lines[i]

                    # 跳过空行和纯空白行
                    if not line.strip():
                        i += 1
                        continue

                    fname = ""
                    fcontent = ""

                    # 检测多行格式：文件名:: 后面直接是换行（内容从下一行开始）
                    if '::' in line:
                        idx = line.index('::')
                        fname = line[:idx].strip()
                        rest = line[idx+2:]  # 双冒号后面的内容

                        if rest:  # 双冒号后面有内容（单行格式）
                            fcontent = rest
                            i += 1
                        else:  # 双冒号后面是换行（多行格式）
                            # 累积多行内容直到 ::END
                            i += 1
                            while i < len(lines):
                                content_line = lines[i]
                                if content_line.strip() == "::END":
                                    i += 1
                                    break
                                if fcontent:
                                    fcontent += '\n'
                                fcontent += content_line
                                i += 1
                    elif ':' in line:
                        # 旧格式（单冒号）
                        idx = line.index(':')
                        fname = line[:idx].strip()
                        fcontent = line[idx+1:]
                        i += 1
                    else:
                        # 没有冒号，整个行作为文件名
                        fname = line.strip()
                        i += 1

                    if not fname:
                        continue

                    # 处理 YAML 风格的换行符
                    fcontent = fcontent.replace('\\n', '\n').replace('\\t', '\t')

                    # 如果 fname 包含路径分隔符，按路径创建
                    fpath = target_dir / fname
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(fcontent, encoding=encoding)
                    # 记录相对于项目目录的路径（用于数据库记录）
                    created_files.append(fname)

            # 6. 更新会话限制（保存创建的项目名）
            if session_id:
                await set_allowed_project_root(session_id, project_folder)
                # 记录创建的文件
                try:
                    from app.agent.tools.session_context import add_session_files
                    file_records = []
                    for fname in created_files:
                        # 判断文件类型
                        file_type = "other"
                        language = None
                        is_entry = False
                        if fname.endswith(".py"):
                            language = "python"
                            file_type = "entrypoint" if fname in ["app.py", "main.py", "run.py", "server.py"] else "dependency"
                        elif fname.endswith((".js", ".ts", ".jsx", ".tsx")):
                            language = "javascript"
                            file_type = "entrypoint" if fname in ["index.js", "main.js", "server.js", "app.js"] else "dependency"
                        elif fname.endswith(".html"):
                            language = "html"
                            file_type = "entrypoint" if fname == "index.html" else "static"
                        elif fname.endswith((".css", ".scss")):
                            language = "css"
                            file_type = "static"
                        elif fname.endswith((".json", ".yaml", ".yml", ".toml")):
                            file_type = "config"

                        file_records.append({
                            "file_path": fname,
                            "absolute_path": str((target_dir / fname).resolve()),
                            "file_type": file_type,
                            "size": 0,  # 暂不计算
                            "language": language,
                            "is_entrypoint": is_entry,
                        })
                    if file_records:
                        await add_session_files(session_id, file_records)
                except Exception as e:
                    logger.debug(f"[FileOps] 记录文件失败: {e}")

            logger.info(f"[FileOps] 创建项目: {target_dir}, {len(created_files)} 个文件")

            return SkillResult(
                success=True,
                data={
                    "path": str(target_dir),
                    "project_name": project_folder,  # 返回带时间戳的项目名，供后续 write 使用
                    "files": created_files,
                    "count": len(created_files)
                },
                metadata={"operation": "create", "task_path": project_folder}
            )
        except Exception as e:
            logger.error(f"[FileOps] 创建项目失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _write_file(self, file_path: str, content: str, encoding: str, task_path: Optional[str] = None, session_id: Optional[str] = None) -> SkillResult:
        """
        写入文件

        路径规则：
        - 优先使用 task_path（来自 create 的返回值）
        - 如果没有 task_path，使用 session 中的 allowed_project_root
        - 最终路径：tasks/{project_name}_{timestamp}/{file_path}

        支持任务中断后继续：
        - 如果 task_path 已存在，直接使用
        - 如果 session 有 allowed_project_root，直接使用
        """
        try:
            # 绝对路径逃逸拦截（2026-11-13 黄金测试集 test_safe_path_check 抓出）：
            # pathlib 拼接时 target_dir / "/x" == "/x" 绕过项目目录，且自动建项目
            # 分支把 path_parts[0]='/' 当项目名 → '/_时间戳' 会写到文件系统根
            if os.path.isabs(file_path):
                _abs_in = str(Path(file_path).resolve())
                if not _abs_in.startswith(str(self._tasks_dir.resolve())):
                    return SkillResult(success=False,
                                       error=f"安全检查失败：禁止写入路径 {file_path}")
            # 1. 确定项目目录
            project_folder = None
            rel_write_path = file_path  # 默认使用原始路径

            if task_path:
                # 优先使用传入的 task_path
                project_folder = task_path
                # 从 task_path 提取项目名（格式: projectname_timestamp）
                # 例如：flask_blog_1234567890 -> 项目名是 flask_blog
                match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)_\d+$', task_path)
                project_name = match.group(1) if match else None

                # 清理 file_path 的前缀
                clean_path = file_path
                # 去除 ./ 前缀
                if clean_path.startswith('./'):
                    clean_path = clean_path[2:]
                # 去除 ../ 前缀
                if clean_path.startswith('../'):
                    clean_path = clean_path[3:]

                # 检查 file_path 是否是完整路径（包含项目名或 task_path）
                # 完整路径格式可能是：
                #   - projectname_timestamp/app.py
                #   - projectname_project/app.py
                #   - 直接是 filename.py
                if project_name:
                    # 构建所有可能的前缀（从长到短排序）
                    prefixes = [
                        f"{project_name}_project/",      # flask_blog_project/
                        f"{project_name}-project/",      # flask_blog-project/
                        f"{project_name}_",              # flask_blog_ (匹配 projectname_timestamp 整体)
                        # 注意：不剥离裸 "{project_name}/" —— 项目恰好同名的子目录
                        # （如 calculator/core.py）会被误压平成 core.py（2026-11-12 修复）
                    ]
                    matched = False
                    for prefix in prefixes:
                        if clean_path.startswith(prefix):
                            rel_write_path = clean_path[len(prefix):]
                            logger.debug(f"[FileOps] 去除项目名前缀: {clean_path} → {rel_write_path}")
                            matched = True
                            break

                    # 如果 clean_path 以完整的 task_path 开头（带时间戳的完整项目名）
                    if not matched and clean_path.startswith(project_folder):
                        rel_write_path = clean_path[len(project_folder):].lstrip('/\\')
                        logger.debug(f"[FileOps] 提取相对路径（基于完整task_path）: {clean_path} → {rel_write_path}")
                        matched = True
                else:
                    rel_write_path = clean_path

            elif self._allowed_project_root:
                # 使用 session 中保存的项目目录
                project_folder = self._allowed_project_root

            # 2. 构建最终路径
            if project_folder:
                target_dir = self._tasks_dir / project_folder
                path = target_dir / rel_write_path if rel_write_path != "." else target_dir
                abs_path = str(path.resolve())

                # 会话限制检查：确保在允许的目录下
                # 优先使用传入的 task_path（已验证是合法的），否则使用 _allowed_project_root
                check_root = task_path or self._allowed_project_root
                if check_root:
                    check_dir = str((self._tasks_dir / check_root).resolve())
                    if not abs_path.startswith(check_dir):
                        return SkillResult(
                            success=False,
                            error=f"错误：路径 '{abs_path}' 不在允许的目录 '{check_dir}' 范围内。"
                        )
            else:
                # 没有项目目录，自动创建一个项目目录
                import time as time_module
                timestamp = int(time_module.time())
                # 尝试从文件路径推断项目名
                path_parts = Path(file_path).parts
                if len(path_parts) > 1:
                    # 有子目录，使用第一个子目录作为项目名
                    project_folder = f"{path_parts[0]}_{timestamp}"
                    rel_write_path = str(Path(*path_parts[1:]))
                else:
                    # 只有文件名，使用 auto_project 作为项目名
                    project_folder = f"auto_project_{timestamp}"
                    rel_write_path = file_path
                target_dir = self._tasks_dir / project_folder
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / rel_write_path
                abs_path = str(path.resolve())
                logger.info(f"[FileOps] 自动创建项目目录: {project_folder}")

            # 3. 验证文件路径是否合法（不能包含Python代码）
            if self._looks_like_python_code(file_path):
                return SkillResult(
                    success=False,
                    error=f"文件路径无效: '{file_path}'。path 必须是合法的文件路径（如 'app.py'），不能包含Python代码。"
                )

            # 4. 安全检查
            if not self._is_safe_path(abs_path):
                return SkillResult(success=False, error=f"安全检查失败：禁止写入路径 {abs_path}")

            # 4. 创建父目录并写入文件
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            logger.info(f"[FileOps] 写入文件: {path}")

            # 5. 记录文件到数据库
            if session_id:
                try:
                    from app.agent.tools.session_context import add_session_file
                    # 判断文件类型
                    file_type = "other"
                    language = None
                    is_entry = False
                    if str(path).endswith(".py"):
                        language = "python"
                        file_type = "entrypoint" if path.name in ["app.py", "main.py", "run.py", "server.py"] else "dependency"
                    elif str(path).endswith((".js", ".ts", ".jsx", ".tsx")):
                        language = "javascript"
                        file_type = "entrypoint" if path.name in ["index.js", "main.js", "server.js", "app.js"] else "dependency"
                    elif str(path).endswith(".html"):
                        language = "html"
                        file_type = "entrypoint" if path.name == "index.html" else "static"
                    elif str(path).endswith((".css", ".scss")):
                        language = "css"
                        file_type = "static"
                    elif str(path).endswith((".json", ".yaml", ".yml", ".toml")):
                        file_type = "config"

                    await add_session_file(
                        session_id=session_id,
                        file_path=rel_write_path,
                        file_type=file_type,
                        absolute_path=str(path.resolve()),
                        size=len(content),
                        language=language,
                        is_entrypoint=is_entry,
                    )
                except Exception as e:
                    logger.debug(f"[FileOps] 记录文件失败: {e}")

            return SkillResult(
                success=True,
                data={"path": str(path), "size": len(content), "project_name": project_folder},
                metadata={"operation": "write", "task_path": project_folder}
            )
        except Exception as e:
            logger.error(f"[FileOps] 写入文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _write_files_batch(self, files, encoding: str,
                                 task_path: Optional[str] = None,
                                 session_id: Optional[str] = None) -> SkillResult:
        """批量并发写入多个互不关联的文件（一次调用替代逐文件多轮）。

        2026-11-13 用户反馈：项目骨架创建时文件一个个写，互不干扰的文件
        完全可以并发批量创建，减少等待轮次。每个文件独立走 _write_file
        （路径解析/安全检查/父目录创建/会话记录全部复用），并发执行；
        单个失败不影响其余文件，结果汇总返回。
        """
        parsed = _parse_files_param(files)
        if isinstance(parsed, SkillResult):
            return parsed
        items = [(f["path"], f["content"]) for f in parsed]

        results = await asyncio.gather(
            *[self._write_file(p, c, encoding, task_path, session_id) for p, c in items],
            return_exceptions=True,
        )
        written, errors = [], []
        for (p, _), r in zip(items, results):
            if isinstance(r, BaseException):
                errors.append(f"{p}: {r}")
            elif getattr(r, "success", False):
                written.append(p)
            else:
                errors.append(f"{p}: {getattr(r, 'error', '未知错误')}")
        logger.info(f"[FileOps] 批量写入 {len(written)}/{len(items)} 个文件"
                    + (f"，{len(errors)} 个失败" if errors else ""))
        if not written:
            return SkillResult(success=False,
                               error="批量写入全部失败：" + "；".join(errors[:5]))
        data = {"files": written, "count": len(written)}
        if errors:
            data["note"] = f"{len(errors)} 个文件失败: " + "；".join(errors[:3])
        return SkillResult(success=True, data=data, metadata={"operation": "write"})

    async def _read_files_batch(self, files, encoding: str,
                                task_path: Optional[str] = None,
                                session_id: Optional[str] = None) -> SkillResult:
        """并行批量读取多个互不关联的文件（files 数组，与 write 对称）。

        2026-11-13 生产实测：模型会自然把 write 的 files 模式推广到 read，
        read 不收就报"缺少 path 参数"浪费一轮——补上并行读取。
        """
        parsed = _parse_files_param(files)
        if isinstance(parsed, SkillResult):
            return parsed
        paths = [f["path"] for f in parsed]
        results = await asyncio.gather(
            *[self._read_file(p, encoding, session_id, task_path, 1, 500)
              for p in paths],
            return_exceptions=True,
        )
        parts, ok, failed = [], [], []
        for p, r in zip(paths, results):
            if isinstance(r, BaseException) or not getattr(r, "success", False):
                err = r if isinstance(r, BaseException) else getattr(r, "error", "未知错误")
                failed.append(f"{p}: {err}")
                continue
            ok.append(p)
            parts.append(f"=== {p} ===\n{(r.data or {}).get('content', '')}")
        if not parts:
            return SkillResult(success=False,
                               error="批量读取全部失败：" + "；".join(failed[:5]))
        logger.info(f"[FileOps] 批量读取 {len(ok)}/{len(paths)} 个文件"
                    + (f"，{len(failed)} 个失败" if failed else ""))
        data = {"files": ok, "count": len(ok),
                "content": "\n\n".join(parts)}
        if failed:
            data["note"] = f"{len(failed)} 个文件读取失败: " + "；".join(failed[:3])
        return SkillResult(success=True, data=data, metadata={"operation": "read"})

    async def _edit_file(self, file_path: str, old_text, new_text, replace_all, encoding: str,
                         session_id: Optional[str] = None, task_path: Optional[str] = None) -> SkillResult:
        """局部替换（edit）：只改 old_text 命中的片段，其余内容不动。
        对齐 Hermes patch 工具——局部改动优先用它，全量 write 仅用于重写级改动。
        """
        if old_text is None or old_text == "":
            return SkillResult(success=False, error="缺少 old_text 参数（待替换的原文片段，需与文件内容逐字一致）")
        if new_text is None:
            return SkillResult(success=False, error="缺少 new_text 参数（替换后的新文本）")
        old_text, new_text = str(old_text), str(new_text)
        if isinstance(replace_all, str):
            replace_all = replace_all.strip().lower() in ("true", "1", "yes")
        replace_all = bool(replace_all)
        # 路径解析与安全检查（与 read 同规则，仅限任务目录）
        project_root = task_path or self._allowed_project_root
        resolved_path = file_path
        if not Path(file_path).is_absolute():
            if project_root:
                resolved_path = str(self._tasks_dir / project_root / file_path)
            else:
                resolved_path = str(self._tasks_dir / file_path)
        if not self._is_safe_read_path(resolved_path):
            return SkillResult(success=False, error=f"安全检查失败：禁止编辑路径 {file_path}")
        path = Path(resolved_path)
        if not path.exists():
            return SkillResult(success=False, error=f"文件不存在: {file_path}（edit 只能改已有文件，新文件请用 write）")
        if path.is_dir():
            return SkillResult(success=False, error=f"路径是目录不是文件: {file_path}")
        try:
            content = path.read_text(encoding=encoding)
        except Exception as e:
            return SkillResult(success=False, error=f"读取文件失败: {e}")
        hits = content.count(old_text)
        if hits == 0:
            return SkillResult(success=False, error=(
                f"在 {file_path} 中未找到待替换文本。old_text 必须与文件内容逐字一致"
                "（含空格、缩进、换行）；先用 search_files 定位或 read 查看原文"))
        if hits > 1 and not replace_all:
            return SkillResult(success=False, error=(
                f"old_text 在文件中命中 {hits} 处（不唯一）。请提供更多上下文使片段唯一，"
                "或显式传 replace_all=true 全部替换"))
        n = hits if replace_all else 1
        new_content = content.replace(old_text, new_text, n)
        try:
            path.write_text(new_content, encoding=encoding)
        except Exception as e:
            return SkillResult(success=False, error=f"写入文件失败: {e}")
        return SkillResult(
            success=True,
            data={
                "operation": "edit",
                "path": str(path),
                "replaced": n,
                "matches": hits,
                "total_lines": len(new_content.splitlines()),
                "size": len(new_content),
            },
        )

    async def _edit_files_batch(self, edits, default_path: str, encoding: str,
                                session_id: Optional[str] = None,
                                task_path: Optional[str] = None) -> SkillResult:
        """批量局部替换（edits 数组）：一次调用完成多文件/多处 edit。

        2026-11-13 用户测试：模型会把 write 的 files 批量模式自然推广到
        edit（发 edits:[{old,new}]），不支持就报"缺少 old_text"白烧轮次。
        每项: {path?, old, new, replace_all?}
        （也兼容 old_text/new_text、old_string/new_string 键——
        2026-11-14 TC-S16-03：模型对 edit 也自然用 OpenAI 风格 old_string），
        path 缺省用顶层 path。同文件多处按顺序应用（有依赖，不并发）。
        """
        if isinstance(edits, str):
            try:
                edits = json.loads(edits)
            except Exception:
                return SkillResult(success=False,
                                   error='edits 必须是 JSON 数组: [{"old": "...", "new": "..."}]')
        if not isinstance(edits, list) or not edits:
            return SkillResult(success=False,
                               error='edits 必须是非空数组: [{"path": "a.py", "old": "...", "new": "..."}]')
        applied, failed = [], []
        for i, e in enumerate(edits):
            if not isinstance(e, dict):
                failed.append(f"edits[{i}]: 必须是对象")
                continue
            p = str(e.get("path") or default_path or "").strip()
            old = e.get("old")
            if old is None:
                old = e.get("old_text")
            if old is None:
                old = e.get("old_string")
            new = e.get("new")
            if new is None:
                new = e.get("new_text")
            if new is None:
                new = e.get("new_string")
            if not p or old is None or new is None:
                failed.append(f"edits[{i}]: 缺少 path/old/new")
                continue
            r = await self._edit_file(p, old, new, bool(e.get("replace_all", False)),
                                      encoding, session_id, task_path)
            if r.success:
                applied.append(p)
            else:
                failed.append(f"{p}: {r.error}")
        if not applied:
            return SkillResult(success=False,
                               error="批量替换全部失败：" + "；".join(failed[:5]))
        data = {"edited": applied, "count": len(applied)}
        if failed:
            data["note"] = f"{len(failed)} 处失败: " + "；".join(failed[:3])
        logger.info(f"[FileOps] 批量替换 {len(applied)}/{len(edits)} 处")
        return SkillResult(success=True, data=data, metadata={"operation": "edit_file"})

    async def _read_file(self, file_path: str, encoding: str, session_id: Optional[str] = None, task_path: Optional[str] = None, offset: int = 1, limit: int = 200) -> SkillResult:
        """读取文件（分页：offset/limit + 行号，2026-11-13 对齐 Hermes 精准读取）"""
        # 优先使用 task_path（从外部传入），否则使用 _allowed_project_root
        project_root = task_path or self._allowed_project_root

        # 尝试解析路径（处理相对路径和项目内路径）
        resolved_path = file_path
        if not Path(file_path).is_absolute():
            # 如果有项目根目录，使用项目目录
            if project_root:
                resolved_path = str(self._tasks_dir / project_root / file_path)
            else:
                resolved_path = str(self._tasks_dir / file_path)

        if not self._is_safe_read_path(resolved_path):
            return SkillResult(success=False, error=f"安全检查失败：禁止读取路径 {file_path}")

        try:
            path = Path(resolved_path)
            if not path.exists():
                # 兼容历史压平写入：calculator/core.py 曾被落成 core.py，
                # 若相对路径以裸项目名开头，剥前缀再试一次（读老文件仍能找到）
                if project_root and not Path(file_path).is_absolute():
                    m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)_\d+$', project_root)
                    parts = Path(file_path).parts
                    if m and len(parts) > 1 and parts[0] == m.group(1):
                        alt = Path(self._tasks_dir) / project_root / Path(*parts[1:])
                        if alt.is_file():
                            logger.info(f"[FileOps] 读取回退到历史压平路径: {alt}")
                            path = alt
            if not path.exists():
                # 改进错误信息：先在任务目录里找同名文件（生产实测 app/extensions.py
                # 存在、模型按裸名 extensions.py 反复读失败 4 次，旧提示还引导
                # write 在根目录建重复文件）——找到就直接给出正确相对路径
                error_msg = f"文件不存在: {file_path}"
                if project_root:
                    error_msg += f"\n项目目录: {project_root}"
                    _hit = ""
                    try:
                        _tr = self._tasks_dir / project_root
                        if _tr.is_dir():
                            for _r, _d, _fs in os.walk(_tr):
                                if Path(file_path).name in _fs:
                                    _hit = str(Path(_r, Path(file_path).name).relative_to(_tr))
                                    break
                    except Exception:
                        _hit = ""
                    if _hit:
                        error_msg += (f"\n同名文件实际位于: {_hit}"
                                      f"——请改用该相对路径重试（path={_hit}）")
                    else:
                        error_msg += ("\n提示: 任务目录中没有此文件（可用 operation='list' 查看"
                                      "目录结构）；如确需创建，用 operation='write' 并写全"
                                      "相对路径（如 app/x.py），不要只写裸文件名")
                return SkillResult(success=False, error=error_msg)
            if path.is_dir():
                return SkillResult(success=False, error=f"路径是目录不是文件: {file_path}")

            content = path.read_text(encoding=encoding)
            max_size = 100 * 1024
            if len(content) > max_size:
                content = content[:max_size] + "\n... (内容过长已截断)"

            # 分页：默认读前 200 行，行号前缀 + 续读提示（先搜后读的精准读取）
            try:
                _off = max(1, int(offset))
            except (TypeError, ValueError):
                _off = 1
            try:
                _lim = min(max(1, int(limit)), 500)
            except (TypeError, ValueError):
                _lim = 200
            _lines = content.splitlines()
            _total = len(_lines)
            _slice = _lines[_off - 1: _off - 1 + _lim]
            _end = _off - 1 + len(_slice)
            _has_more = _end < _total
            _numbered = "\n".join(
                f"{i:>5}| {ln}"
                for i, ln in zip(range(_off, _off + len(_slice)), _slice)
            )
            _footer = (
                f"\n[共 {_total} 行，显示 {_off}-{_end if _slice else 0}"
                + ("，还有更多：用 offset 续读下一段" if _has_more else "，已到文件末尾")
                + "。行号仅用于定位，写回文件时不要带行号]"
            )

            return SkillResult(
                success=True,
                data={
                    "content": _numbered + _footer,
                    "size": len(content),
                    "path": resolved_path,
                    "offset": _off,
                    "limit": _lim,
                    "total_lines": _total,
                    "has_more": _has_more,
                    "next_offset": _end + 1 if _has_more else None,
                },
                metadata={"operation": "read"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 读取文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _list_directory(self, dir_path: str, task_path: Optional[str] = None) -> SkillResult:
        """列出目录（相对路径基于任务目录，与 read 同规则——修复丢 task_path 落到 tasks 根）"""
        try:
            project_root = task_path or self._allowed_project_root
            path = Path(dir_path)
            abs_path = dir_path

            if not path.is_absolute():
                if project_root:
                    path = self._tasks_dir / project_root / dir_path
                else:
                    path = self._tasks_dir / dir_path
                abs_path = str(path.resolve())

            if not self._is_safe_path(abs_path):
                return SkillResult(success=False, error=f"安全检查失败：禁止访问路径 {abs_path}")

            if not path.exists():
                error_msg = f"目录不存在: {abs_path}"
                if project_root and not Path(dir_path).is_absolute():
                    error_msg += f"\n项目目录: {project_root}"
                    error_msg += "\n提示: 相对路径基于任务目录；先用 operation='list', path='.' 查看现有结构"
                return SkillResult(success=False, error=error_msg)
            if not path.is_dir():
                return SkillResult(success=False, error=f"路径是文件不是目录: {abs_path}")

            items = []
            for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                if item.name.startswith('.'):
                    continue
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                })

            return SkillResult(
                success=True,
                data={"items": items, "path": abs_path, "count": len(items)},
                metadata={"operation": "list"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 列出目录失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _delete_file(self, file_path: str, task_path: Optional[str] = None) -> SkillResult:
        """删除文件（相对路径基于任务目录——修复丢 task_path 误删 tasks 根同名文件）"""
        try:
            project_root = task_path or self._allowed_project_root
            path = Path(file_path)
            abs_path = file_path

            if not path.is_absolute():
                if project_root:
                    path = self._tasks_dir / project_root / file_path
                else:
                    path = self._tasks_dir / file_path
                abs_path = str(path.resolve())

            if not self._is_safe_path(abs_path):
                return SkillResult(success=False, error=f"安全检查失败：禁止删除路径 {abs_path}")

            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {abs_path}")

            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()
                # 文件删光后父目录变空也清掉（同 move 的收尾原则）。
                # 级联向上：删 app/static/css/x.css 后依次空出 css→static→app。
                # 2026-11-13 TC-S16-01 取证：只 rmdir 一次直接父目录时，
                # 子目录被清空（无新 unlink 事件发生在父目录）→ 空目录树残留。
                try:
                    root = (self._tasks_dir / project_root).resolve() if project_root else None
                    parent = path.parent
                    while root and parent != root and parent.is_relative_to(root):
                        try:
                            parent.rmdir()   # 非空会抛 OSError → break，绝不动非空目录
                        except OSError:
                            break
                        logger.info(f"[FileOps] 清理删空的父目录: {parent}")
                        parent = parent.parent
                except OSError:
                    pass

            logger.info(f"[FileOps] 删除: {path}")
            return SkillResult(
                success=True,
                data={"path": abs_path, "deleted": True},
                metadata={"operation": "delete"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 删除文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _move_files_batch(self, files, task_path: Optional[str] = None) -> SkillResult:
        """批量移动（files 数组）：一次搬多个文件，串行执行。

        2026-11-13 生产取证：重构/归类任务里模型自然把批量模式推广到 move
        （files=[{path,destination}]、{from,to}、{src,dst} 混用），原先不收
        就报"缺少 path 参数"×7，只能逐个补搬、烧掉轮次还漏搬（根目录残留）。
        元素键兼容 path/from/src/source + dest/destination/to/dst/target_path。
        单个失败不影响其余；全部失败才 success=False。
        """
        if not isinstance(files, list):
            return SkillResult(success=False, error="move 的 files 必须是数组")
        pairs = []
        bad = []
        for i, item in enumerate(files):
            if not isinstance(item, dict):
                bad.append(f"第{i + 1}项不是对象")
                continue
            src = (item.get("path") or item.get("from") or item.get("src")
                   or item.get("source"))
            dst = (item.get("destination") or item.get("dest") or item.get("to")
                   or item.get("dst") or item.get("target_path"))
            if not src or not dst:
                bad.append(f"第{i + 1}项缺少源/目标（path/from + dest/to）")
                continue
            pairs.append((str(src), str(dst)))
        if not pairs and bad:
            return SkillResult(success=False,
                               error="批量移动参数无效：" + "；".join(bad[:5]))
        moved, errors = [], list(bad)
        for src, dst in pairs:
            r = await self._move_file(src, dst, task_path)
            if getattr(r, "success", False):
                moved.append({"from": src, "to": dst})
            else:
                errors.append(f"{src}: {getattr(r, 'error', '未知错误')}")
        # 收尾：自底向上清掉整棵被搬空的目录树（顺序造成的空壳残留）
        try:
            root = (self._tasks_dir / task_path).resolve() if task_path else None
            if root and root.is_dir():
                _dirs = sorted([p for p in root.rglob("*") if p.is_dir()],
                               key=lambda p: len(p.parts), reverse=True)
                for _r in _dirs:
                    try:
                        _r.rmdir()  # 非空自动失败，安全
                    except OSError:
                        pass
        except Exception:
            pass
        logger.info(f"[FileOps] 批量移动 {len(moved)}/{len(pairs)} 个文件"
                    + (f"，{len(errors)} 个失败" if errors else ""))
        if not moved:
            return SkillResult(success=False,
                               error="批量移动全部失败：" + "；".join(errors[:5]))
        data = {"moved": moved, "count": len(moved)}
        if errors:
            data["note"] = f"{len(errors)} 项失败: " + "；".join(errors[:3])
        return SkillResult(success=True, data=data, metadata={"operation": "move"})

    async def _delete_files_batch(self, files, task_path: Optional[str] = None,
                                  session_id: Optional[str] = None,
                                  friendly_action: Optional[str] = None) -> SkillResult:
        """批量删除：files=[{path|delete|file}] 或 paths=["a","b"]（字符串列表）。

        与批量 move 同语义：串行执行、单个失败进 note 不中断、全部失败才 False。
        """
        ok, errs = 0, []
        for i, item in enumerate(files):
            if isinstance(item, str):
                p = item
            elif isinstance(item, dict):
                p = (item.get("path") or item.get("delete")
                     or item.get("file") or item.get("src"))
            else:
                p = None
            if not p:
                errs.append(f"第{i+1}项缺少 path 参数")
                continue
            try:
                r = await self._delete_file(p, task_path)
                if r.success:
                    ok += 1
                else:
                    errs.append(f"{p}: {r.error}")
            except Exception as e:  # noqa: BLE001
                errs.append(f"{p}: {e}")
        # 收尾：自底向上清掉整棵空目录树——批量删除顺序会造成
        # "子目录先空、父目录没有自己的 unlink 事件"的残留（app/static、
        # app/templates 空壳）。rmdir 只删空目录，非空自动失败，根目录不碰。
        try:
            _root = (self._tasks_dir / task_path).resolve() if task_path else None
            if _root and _root.is_dir():
                _dirs = [Path(_r) for _r, _ds, _fs in os.walk(_root)]
                for _d in sorted(_dirs, key=lambda x: len(x.parts), reverse=True):
                    if _d == _root:
                        continue
                    try:
                        _d.rmdir()
                    except OSError:
                        pass
        except Exception:  # noqa: BLE001
            pass
        if errs and not ok:
            return SkillResult(success=False, error="批量删除失败：" + "; ".join(errs[:6]))
        note = f"批量删除 {ok}/{len(files)} 成功"
        if errs:
            note += f"，失败 {len(errs)} 项: " + "; ".join(errs[:6])
        return SkillResult(success=True, data={"deleted": ok, "count": ok,
                                               "note": note},
                           metadata={"session_id": session_id, "operation": "delete",
                                     "batch_count": ok,
                                     "friendly_action": friendly_action or "批量删除文件"})

    @staticmethod
    def _strip_task_prefix(rel: str, task_path: str) -> str:
        """剥掉相对路径里的任务目录名前缀。

        覆盖两种模型常见写法：`<task>/app/x.py` 与 `tasks/<task>/app/x.py`。
        剥完为空（path 恰等于任务目录名）则保留原值——create/list 的 path
        就是任务目录本身，不能剥空。
        """
        if not isinstance(rel, str) or not rel or rel.startswith(("/", "~")):
            return rel
        parts = Path(rel).parts
        if parts and parts[0] == task_path:
            rest = parts[1:]
            if rest:
                return str(Path(*rest))
        elif len(parts) >= 2 and parts[0] == "tasks" and parts[1] == task_path:
            rest = parts[2:]
            if rest:
                return str(Path(*rest))
        return rel

    def _strip_task_prefix_kwargs(self, kwargs: Dict[str, Any], task_path: str) -> Dict[str, Any]:
        """对一次工具调用的所有路径键做前缀剥离（顶层 + 批量元素）。"""
        out = dict(kwargs)
        for key in ("path", "dest", "to", "from", "src", "file_path", "output_path"):
            v = out.get(key)
            if isinstance(v, str):
                out[key] = self._strip_task_prefix(v, task_path)
        for key in ("files", "paths"):
            arr = out.get(key)
            if not isinstance(arr, list) or not arr:
                continue
            new_arr = []
            changed = False
            for it in arr:
                if isinstance(it, str):
                    n = self._strip_task_prefix(it, task_path)
                    changed = changed or n != it
                    new_arr.append(n)
                elif isinstance(it, dict):
                    it2 = dict(it)
                    for k in ("path", "from", "src", "dest", "to"):
                        v = it2.get(k)
                        if isinstance(v, str):
                            n = self._strip_task_prefix(v, task_path)
                            if n != v:
                                it2[k] = n
                                changed = True
                    new_arr.append(it2)
                else:
                    new_arr.append(it)
            if changed:
                out[key] = new_arr
        return out

    def _resolve_move_path(self, file_path: str, task_path: Optional[str]) -> Path:
        """移动/删除同规则的路径解析：相对路径基于任务目录"""
        p = Path(file_path)
        if not p.is_absolute():
            project_root = task_path or self._allowed_project_root
            if project_root:
                p = self._tasks_dir / project_root / file_path
            else:
                p = self._tasks_dir / file_path
        return p

    async def _move_file(self, file_path: str, dest: str, task_path: Optional[str] = None) -> SkillResult:
        """移动/归类文件或目录：原子移动，源在原位置消失（不是复制）。

        path=源，dest=目标（均相对任务目录）。目标已存在时按 shell mv 语义覆盖
        （源是权威文件，目标只是归类落点），目录冲突才拒绝。
        归类/整理/迁移类任务必须用本操作——在目标位置新建副本不算移动。
        """
        try:
            src = self._resolve_move_path(file_path, task_path)
            if not self._is_safe_path(str(src.resolve())):
                return SkillResult(success=False, error=f"安全检查失败：禁止移动路径 {src}")
            if not src.exists():
                return SkillResult(success=False, error=f"源文件不存在: {src}")

            dst = self._resolve_move_path(dest, task_path)
            if not self._is_safe_path(str(dst.resolve())):
                return SkillResult(success=False, error=f"安全检查失败：禁止移动到 {dst}")

            if src.resolve() == dst.resolve():
                return SkillResult(
                    success=True,
                    data={"from": str(src), "to": str(dst), "moved": False,
                          "note": "源与目标相同，无需移动"},
                    metadata={"operation": "move"},
                )
            note = ""
            if dst.exists():
                # 目标已存在：按 shell mv 语义覆盖。
                # （2026-11-13 生产两轮实测：内容不同时拒绝会让模型绕进
                #  read 比对 / write 改写的死循环，16 轮烧完仍失败；
                #  源是用户指定要移动的权威文件，目标只是归类落点，覆盖即移动）
                if dst.is_dir() or src.is_dir():
                    return SkillResult(success=False,
                                       error=f"目标已存在（目录），拒绝覆盖: {dest}"
                                             f"（先删除目标目录或换一个目标名）")
                if dst.stat().st_size > 0 and dst.read_bytes() != src.read_bytes():
                    note = "已覆盖目标原有不同内容"

            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                src.replace(dst)                      # 同文件系统：原子移动
            except OSError:
                shutil.move(str(src), str(dst))       # 跨文件系统回退
            if not dst.exists():
                return SkillResult(success=False, error=f"移动失败，目标不存在: {dst}")

            # 源目录被搬空则顺手删除（2026-11-13 用户反馈：改造任务原文件都
            # 搬走了，旧空文件夹残留——move 文档/提示词/完成校验原本都没提
            # "搬空清目录"，模型逐个搬完不会自发删）。os.rmdir 只删空目录
            # （非空抛 OSError 跳过），且必须在任务目录内、不碰任务根，安全。
            # 级联向上：搬空 app/static/css/x.css 后依次空出 css→static→app
            # （2026-11-13 TC-S16-01：只 rmdir 一次直接父目录，层层空出的
            # 祖先目录没有自己的搬空事件，app/static 空壳残留根因）。
            try:
                root = (self._tasks_dir / task_path).resolve() if task_path else None
                parent = src.parent
                while root and parent != root and parent.is_relative_to(root):
                    try:
                        parent.rmdir()
                    except OSError:
                        break  # 仍有其他内容/无权限 → 停止上溯
                    rel = str(parent.relative_to(root))
                    note = f"{note}；已清理空目录 {rel}" if note else f"已清理空目录 {rel}"
                    logger.info(f"[FileOps] 清理搬空的源目录: {parent}")
                    parent = parent.parent
            except OSError:
                pass  # 边界异常 → 保留

            logger.info(f"[FileOps] 移动: {src} -> {dst}（{note or '新建目标'}）")
            return SkillResult(
                success=True,
                data={"from": str(src), "to": str(dst), "moved": True,
                      **({"note": note} if note else {})},
                metadata={"operation": "move"},
            )
        except Exception as e:
            logger.error(f"[FileOps] 移动文件失败: {e}")
            return SkillResult(success=False, error=str(e))


# 导出 Skill 实例
skill = FileOperationsSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
