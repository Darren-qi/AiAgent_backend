"""内置 Skill - 文件操作"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any

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

    async def execute(self, **kwargs) -> SkillResult:
        operation = kwargs.get("operation", "").lower()
        file_path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        encoding = kwargs.get("encoding", "utf-8")

        if not file_path:
            return SkillResult(success=False, error="缺少 path 参数")

        if operation == "read":
            return await self._read_file(file_path, encoding)
        elif operation == "write":
            return await self._write_file(file_path, content, encoding)
        elif operation == "list":
            return await self._list_directory(file_path)
        elif operation == "delete":
            return await self._delete_file(file_path)
        else:
            return SkillResult(success=False, error=f"不支持的操作: {operation}")

    async def _read_file(self, file_path: str, encoding: str) -> SkillResult:
        """读取文件"""
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

    async def _write_file(self, file_path: str, content: str, encoding: str) -> SkillResult:
        """写入文件"""
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=encoding)

            return SkillResult(
                success=True,
                data={"path": file_path, "size": len(content)},
                metadata={"operation": "write"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 写入文件失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _list_directory(self, dir_path: str) -> SkillResult:
        """列出目录"""
        try:
            path = Path(dir_path)
            if not path.exists():
                return SkillResult(success=False, error=f"目录不存在: {dir_path}")

            if not path.is_dir():
                return SkillResult(success=False, error=f"路径是文件不是目录: {dir_path}")

            items = []
            for item in path.iterdir():
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
        try:
            path = Path(file_path)
            if not path.exists():
                return SkillResult(success=False, error=f"文件不存在: {file_path}")

            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()

            return SkillResult(
                success=True,
                data={"path": file_path, "deleted": True},
                metadata={"operation": "delete"}
            )
        except Exception as e:
            logger.error(f"[FileOps] 删除文件失败: {e}")
            return SkillResult(success=False, error=str(e))
