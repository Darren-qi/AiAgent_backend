"""File Operations Skill - 文件操作技能"""

import os
import json
import re
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from app.agent.skills.core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


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
    backend_dir = module_path.parent.parent.parent.parent
    return backend_dir.parent


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


class FileOperationsSkill(BaseSkill):
    """文件操作 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "operation", "type": "string", "required": True, "description": "操作类型，可选值: write(写文件), create(创建项目目录), read(读文件), list(列目录), delete(删除文件), update(增量更新)。注意: 不要使用 create_directory/create_file/mkdir 等无效值！"},
        {"name": "path", "type": "string", "required": True, "description": "文件路径"},
        {"name": "content", "type": "string", "required": False, "description": "写入内容（write/create/update操作时需要）"},
        {"name": "encoding", "type": "string", "required": False, "description": "文件编码", "default": "utf-8"},
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
        # 编辑文件（增量更新）
        "edit_file": "update",
        "modify_file": "update",
        "update_file": "update",
        "patch": "update",
        "increment_update": "update",
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
    }

    async def execute(self, **kwargs) -> SkillResult:
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
            "update": "patch_file",
        }
        friendly_action = operation_names.get(operation, "file_operations")

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
            result = await self._read_file(file_path, encoding, session_id, task_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "read_file"
            return result
        elif operation == "list":
            result = await self._list_directory(file_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "list_dir"
            return result
        elif operation == "delete":
            if not file_path:
                return SkillResult(success=False, error="缺少 path 参数")
            result = await self._delete_file(file_path)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "delete_file"
            return result
        elif operation == "update":
            if not file_path:
                return SkillResult(success=False, error="缺少 path 参数")
            result = await self._update_file(file_path, content, encoding, task_path, session_id)
            result.metadata = result.metadata or {}
            result.metadata["friendly_action"] = friendly_action
            result.metadata["operation"] = "patch_file"
            return result
        else:
            valid_ops = ", ".join(sorted(set(self._OPERATION_ALIASES.keys()) + ["write", "create", "read", "list", "delete", "update"]))
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
                        f"{project_name}_",             # flask_blog_ (匹配 projectname_timestamp 整体)
                        f"{project_name}/",             # flask_blog/
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
                # 没有项目目录，直接在 tasks 下创建
                path = Path(file_path)
                if path.is_absolute():
                    abs_path = file_path
                else:
                    path = self._tasks_dir / file_path
                    abs_path = str(path.resolve())

            # 3. 安全检查
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
                data={"path": str(path), "size": len(content)},
                metadata={"operation": "write", "task_path": project_folder}
            )
        except Exception as e:
            logger.error(f"[FileOps] 写入文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _read_file(self, file_path: str, encoding: str, session_id: Optional[str] = None, task_path: Optional[str] = None) -> SkillResult:
        """读取文件"""
        # 优先使用 task_path（从外部传入），否则使用 _allowed_project_root（从 session 加载）
        project_root = task_path or self._allowed_project_root

        # 尝试解析路径（处理相对路径和项目内路径）
        resolved_path = file_path
        if not Path(file_path).is_absolute():
            # 如果有项目根目录，检查 file_path 是否已包含项目根目录
            if project_root:
                # 如果 file_path 以 project_root 开头，则认为是相对于 tasks 目录的路径
                # 例如：file_path = "flask_blog_1234567890/app.py", project_root = "flask_blog_1234567890"
                # 应该解析为 tasks/flask_blog_1234567890/app.py
                if file_path.startswith(project_root):
                    # 去除开头的 project_root 部分
                    rel_path = file_path[len(project_root):].lstrip('/\\')
                    resolved_path = str(self._tasks_dir / project_root / rel_path)
                else:
                    # file_path 不包含 project_root，认为是相对于项目目录的路径
                    resolved_path = str(self._tasks_dir / project_root / file_path)
            else:
                resolved_path = str(self._tasks_dir / file_path)

        if not self._is_safe_read_path(resolved_path):
            return SkillResult(success=False, error=f"安全检查失败：禁止读取路径 {file_path}")

        try:
            path = Path(resolved_path)
            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")
            if path.is_dir():
                return SkillResult(success=False, error=f"路径是目录不是文件: {file_path}")

            content = path.read_text(encoding=encoding)
            max_size = 100 * 1024
            if len(content) > max_size:
                content = content[:max_size] + "\n... (内容过长已截断)"

            return SkillResult(
                success=True,
                data={"content": content, "size": len(content), "path": resolved_path},
                metadata={"operation": "read"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 读取文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _list_directory(self, dir_path: str) -> SkillResult:
        """列出目录"""
        try:
            path = Path(dir_path)
            abs_path = dir_path

            if not path.is_absolute():
                path = self._tasks_dir / dir_path
                abs_path = str(path.resolve())

            if not self._is_safe_path(abs_path):
                return SkillResult(success=False, error=f"安全检查失败：禁止访问路径 {abs_path}")

            if not path.exists():
                return SkillResult(success=False, error=f"目录不存在: {abs_path}")
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

    async def _delete_file(self, file_path: str) -> SkillResult:
        """删除文件"""
        try:
            path = Path(file_path)
            abs_path = file_path

            if not path.is_absolute():
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

            logger.info(f"[FileOps] 删除: {path}")
            return SkillResult(
                success=True,
                data={"path": abs_path, "deleted": True},
                metadata={"operation": "delete"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 删除文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _update_file(self, file_path: str, content: str, encoding: str, task_path: Optional[str] = None, session_id: Optional[str] = None) -> SkillResult:
        """
        增量更新文件（支持 diff 格式）

        支持的更新模式：
        1. 完整内容替换：如果 content 不包含 <<<<<<< 和 >>>>>>，则直接替换整个文件
        2. Diff 格式更新：如果 content 包含 <<<<<<< HEAD 和 ======= 和 >>>>>>>，
           则解析 diff 并应用变更

        Diff 格式示例：
        <<<<<<< HEAD
        # 现有内容
        =======
        # 新增/修改内容
        >>>>>>>
        """
        try:
            # 1. 确定文件路径（与 _write_file 相同逻辑）
            project_folder = None
            rel_write_path = file_path

            if task_path:
                project_folder = task_path
                match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)_\d+$', task_path)
                project_name = match.group(1) if match else None

                clean_path = file_path
                if clean_path.startswith('./'):
                    clean_path = clean_path[2:]
                if clean_path.startswith('../'):
                    clean_path = clean_path[3:]

                if project_name:
                    prefixes = [
                        f"{project_name}_project/",
                        f"{project_name}-project/",
                        f"{project_name}_",
                        f"{project_name}/",
                    ]
                    matched = False
                    for prefix in prefixes:
                        if clean_path.startswith(prefix):
                            rel_write_path = clean_path[len(prefix):]
                            matched = True
                            break
                    if not matched and clean_path.startswith(project_folder):
                        rel_write_path = clean_path[len(project_folder):].lstrip('/\\')
                        matched = True

            elif self._allowed_project_root:
                project_folder = self._allowed_project_root

            # 2. 构建最终路径
            if project_folder:
                target_dir = self._tasks_dir / project_folder
                path = target_dir / rel_write_path if rel_write_path != "." else target_dir
                abs_path = str(path.resolve())

                check_root = task_path or self._allowed_project_root
                if check_root:
                    check_dir = str((self._tasks_dir / check_root).resolve())
                    if not abs_path.startswith(check_dir):
                        return SkillResult(
                            success=False,
                            error=f"错误：路径 '{abs_path}' 不在允许的目录 '{check_dir}' 范围内。"
                        )
            else:
                path = Path(file_path)
                if path.is_absolute():
                    abs_path = file_path
                else:
                    path = self._tasks_dir / file_path
                    abs_path = str(path.resolve())

            # 3. 安全检查
            if not self._is_safe_path(abs_path):
                return SkillResult(success=False, error=f"安全检查失败：禁止写入路径 {abs_path}")

            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")

            # 4. 读取现有内容
            existing_content = path.read_text(encoding=encoding)

            # 5. 解析 diff 格式并应用
            new_content = self._apply_diff(existing_content, content)

            # 6. 写入更新后的内容
            path.write_text(new_content, encoding=encoding)
            logger.info(f"[FileOps] 增量更新文件: {path}")

            # 7. 记录文件到数据库
            if session_id:
                try:
                    from app.agent.tools.session_context import add_session_file
                    await add_session_file(
                        session_id=session_id,
                        file_path=rel_write_path,
                        file_type="dependency",
                        absolute_path=str(path.resolve()),
                        size=len(new_content),
                        language=None,
                        is_entrypoint=False,
                    )
                except Exception as e:
                    logger.debug(f"[FileOps] 记录文件失败: {e}")

            return SkillResult(
                success=True,
                data={"path": str(path), "size": len(new_content), "updated": True},
                metadata={"operation": "update", "task_path": project_folder}
            )
        except Exception as e:
            logger.error(f"[FileOps] 增量更新文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _apply_diff(self, existing_content: str, diff_content: str) -> str:
        """
        应用 diff 格式的更新

        支持的 diff 标记：
        - <<<<<<< HEAD: 现有内容开始
        - =======: 分隔现有内容和新内容
        - >>>>>>>: 新内容结束

        如果不包含 diff 标记，则直接返回 diff_content（全量替换）
        """
        # 检查是否包含 diff 标记
        if '<<<<<<< HEAD' not in diff_content or '=======' not in diff_content or '>>>>>>>' not in diff_content:
            # 没有 diff 标记，直接替换
            return diff_content

        # 解析 diff 格式
        lines = diff_content.split('\n')
        result_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]

            if line.startswith('<<<<<<<'):
                # 找到现有内容的开始，查找 ======= 分隔符
                i += 1
                existing_lines = []
                new_lines = []

                while i < len(lines):
                    curr = lines[i]
                    if curr.startswith('======='):
                        i += 1
                        break
                    existing_lines.append(curr)
                    i += 1

                # 收集新内容
                while i < len(lines):
                    curr = lines[i]
                    if curr.startswith('>>>>>>>'):
                        i += 1
                        break
                    new_lines.append(curr)
                    i += 1

                # 使用新内容替换
                result_lines.extend(new_lines)
            else:
                result_lines.append(line)
                i += 1

        return '\n'.join(result_lines)


# 导出 Skill 实例
skill = FileOperationsSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
