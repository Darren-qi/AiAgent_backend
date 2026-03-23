"""内置 Skill - 文件操作"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from app.agent.skills.base import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class FileOperationsSkill(BaseSkill):
    """文件操作 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "file_operations"
        self.description = "文件读写、目录操作"
        self.parameters = [
            {"name": "operation", "type": "string", "required": True, "description": "操作: read/write/list/delete"},
            {"name": "path", "type": "string", "required": True, "description": "文件路径"},
            {"name": "content", "type": "string", "required": False, "description": "写入内容(write操作时必需)"},
            {"name": "encoding", "type": "string", "required": False, "description": "文件编码，默认 utf-8"},
        ]
        # 获取 backend 目录的绝对路径
        # __file__ = backend/app/agent/skills/builtin/file_operations.py
        # 4个parent到达 backend/ 目录
        self._backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
        # 获取 AiAgent 根目录（backend 的父目录）
        self._project_root = self._backend_dir.parent

    def _is_safe_path(self, file_path: str) -> bool:
        """
        检查路径是否安全

        安全路径规则：
        1. 禁止在 backend 目录内
        2. 禁止在 backend 子目录内
        3. 禁止访问系统敏感路径
        """
        try:
            resolved = Path(file_path).resolve()

            # 检查是否在 backend 目录内
            if resolved.is_relative_to(self._backend_dir):
                logger.error(f"[FileOps] 安全检查失败：路径 {file_path} 在 backend 目录 {self._backend_dir} 内")
                return False

            # 检查是否在 AiAgent 根目录下（允许在 tasks 等目录）
            # 这个检查留空，允许 tasks 目录

            # 禁止访问系统敏感路径
            forbidden = ["/etc", "/var", "/usr", "/root", "/home", "/proc", "/sys", "C:\\Windows", "C:\\Program Files"]
            for forbidden_path in forbidden:
                if str(resolved).startswith(forbidden_path):
                    logger.error(f"[FileOps] 安全检查失败：禁止访问系统路径 {forbidden_path}")
                    return False

            return True
        except Exception as e:
            logger.error(f"[FileOps] 路径检查异常: {e}")
            return False

    def _get_allowed_base_dir(self) -> Path:
        """获取允许的基础目录（AiAgent 根目录）"""
        return self._project_root

    async def execute(self, **kwargs) -> SkillResult:
        operation = kwargs.get("operation", "").lower()
        file_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")
        task_path = kwargs.get("task_path")  # 来自 ExecutionContext

        if not file_path:
            return SkillResult(success=False, error="缺少 path 参数")

        # 对于写操作，将相对路径重定向到 task_path 目录
        if operation == "write":
            return await self._write_file(file_path, content, encoding, task_path)
        elif operation == "read":
            return await self._read_file(file_path, encoding)
        elif operation == "list":
            return await self._list_directory(file_path)
        elif operation == "delete":
            return await self._delete_file(file_path)
        else:
            return SkillResult(success=False, error=f"不支持的操作: {operation}")

    async def _read_file(self, file_path: str, encoding: str) -> SkillResult:
        """读取文件"""
        # 安全检查：只允许读取 tasks 和项目目录
        if not self._is_safe_read_path(file_path):
            return SkillResult(
                success=False,
                error=f"安全检查失败：禁止读取路径 {file_path}（禁止读取 backend 目录内的文件）"
            )

        try:
            path = Path(file_path)
            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")

            if path.is_dir():
                return SkillResult(success=False, error=f"路径是目录不是文件: {file_path}")

            content = path.read_text(encoding=encoding)
            # 限制返回内容大小
            max_size = 100 * 1024  # 100KB
            if len(content) > max_size:
                content = content[:max_size] + "\n... (内容过长已截断)"

            return SkillResult(
                success=True,
                data={"content": content, "size": len(content), "path": file_path},
                metadata={"operation": "read"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 读取文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _write_file(self, file_path: str, content: str, encoding: str, task_path: Optional[str] = None) -> SkillResult:
        """写入文件，强制写到 task_path 目录下"""
        # 安全检查：禁止写入 backend 目录
        if not self._is_safe_path(file_path):
            return SkillResult(
                success=False,
                error=f"安全检查失败：禁止写入路径 {file_path}。"
                      f"文件必须保存在 AiAgent/tasks/ 或其他非 backend 目录下。"
            )

        try:
            path = Path(file_path)
            rel_write_path = file_path  # 记录实际写入的相对路径

            # 如果传入了 task_path，将文件写入到 tasks 目录下的任务文件夹
            if task_path and not path.is_absolute():
                # 提取项目名（task_path 格式：项目名_时间戳）
                # 比如 task_path = "flask_blog_1742659200000"，项目名 = "flask_blog"
                import re
                match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)_\d+$', task_path)
                project_name_from_task = match.group(1) if match else None

                # 如果 file_path 以 "项目名/" 开头，说明 LLM 重复添加了项目名
                # 去掉这个前缀，直接写入到 task_path 下
                if project_name_from_task:
                    for prefix in [
                        f"{project_name_from_task}/",
                        f"{project_name_from_task}_project/",
                        f"{project_name_from_task}-project/",
                    ]:
                        if file_path.startswith(prefix):
                            rel_write_path = file_path[len(prefix):]
                            logger.info(f"[FileOps] 去除重复项目前缀: {file_path} -> {rel_write_path}")
                            break

                # 构建最终路径：tasks/task_path/rel_write_path
                target_dir = self._project_root / "tasks" / task_path
                path = target_dir / rel_write_path
            elif not path.is_absolute():
                # 没有 task_path：相对路径写到项目根目录下的 tasks/
                path = self._project_root / "tasks" / file_path

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)
            logger.info(f"[FileOps] 安全写入文件: {path}")

            return SkillResult(
                success=True,
                data={
                    "path": str(path),
                    "size": len(content),
                    "rel_path": str(path.relative_to(self._project_root)) if self._is_safe_path(path) else None
                },
                metadata={"operation": "write", "task_path": task_path}
            )
        except Exception as e:
            logger.error(f"[FileOps] 写入文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _list_directory(self, dir_path: str) -> SkillResult:
        """列出目录"""
        # 安全检查：禁止列出 backend 目录
        if not self._is_safe_path(dir_path):
            return SkillResult(
                success=False,
                error=f"安全检查失败：禁止访问路径 {dir_path}"
            )

        try:
            path = Path(dir_path)
            if not path.exists():
                return SkillResult(success=False, error=f"目录不存在: {dir_path}")

            if not path.is_dir():
                return SkillResult(success=False, error=f"路径是文件不是目录: {dir_path}")

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
                data={"items": items, "path": dir_path, "count": len(items)},
                metadata={"operation": "list"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 列出目录失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _delete_file(self, file_path: str) -> SkillResult:
        """删除文件"""
        # 安全检查：禁止删除 backend 目录内的文件
        if not self._is_safe_path(file_path):
            return SkillResult(
                success=False,
                error=f"安全检查失败：禁止删除路径 {file_path}"
            )

        try:
            path = Path(file_path)
            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")

            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()

            logger.info(f"[FileOps] 安全删除: {path}")
            return SkillResult(
                success=True,
                data={"path": file_path, "deleted": True},
                metadata={"operation": "delete"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 删除文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _is_safe_read_path(self, file_path: str) -> bool:
        """检查读取路径是否安全"""
        try:
            resolved = Path(file_path).resolve()

            # 禁止读取 backend 目录内的文件
            if resolved.is_relative_to(self._backend_dir):
                logger.error(f"[FileOps] 安全检查失败：禁止读取 backend 目录内的文件 {file_path}")
                return False

            # 禁止读取系统文件
            forbidden = ["/etc", "/var", "/usr", "/root", "/home", "/proc", "/sys", "C:\\Windows", "C:\\Program Files"]
            for forbidden_path in forbidden:
                if str(resolved).startswith(forbidden_path):
                    logger.error(f"[FileOps] 安全检查失败：禁止读取系统路径 {forbidden_path}")
                    return False

            return True
        except Exception:
            return False
