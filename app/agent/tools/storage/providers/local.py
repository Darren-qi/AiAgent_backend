"""本地存储"""

import os
import time
import uuid
import aiofiles
from pathlib import Path
from typing import Optional, Dict, Any, List
from app.agent.tools.storage.providers.base import BaseStorageProvider

import logging
logger = logging.getLogger(__name__)


class LocalStorageProvider(BaseStorageProvider):
    """本地文件系统存储

    统一存储路径: AiAgent/tasks/<项目名>_<时间戳>/
    所有文件必须存放在 backend 目录之外。
    """

    def __init__(self):
        # 统一使用 tasks 目录作为根目录（位于 backend 同级的 AiAgent 目录内）
        # 计算项目根目录（AiAgent 的上一级）
        # local.py 在 backend/app/agent/tools/storage/providers/ 下
        # 6个parent -> backend/，7个parent -> AiAgent/，8个parent -> E:/Projects/
        module_path = Path(__file__).resolve()
        backend_dir = module_path.parents[5]  # 6个parent -> backend/
        # 项目根目录 = backend 的上两级（AiAgent/ -> Projects/）
        project_root = backend_dir.parent.parent
        default_tasks = project_root / "tasks"

        storage_path = os.environ.get("LOCAL_STORAGE_PATH")
        if storage_path:
            if os.path.isabs(storage_path):
                self.base_path = Path(storage_path)
            else:
                # 相对路径基于 backend 目录
                self.base_path = backend_dir / storage_path
        else:
            self.base_path = default_tasks

        self.backend_dir = backend_dir

        # 安全检查：确保 base_path 在 backend 目录之外
        self._validate_path()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _validate_path(self):
        """验证路径安全性：禁止在 backend 目录内创建文件"""
        resolved_base = self.base_path.resolve()
        resolved_backend = self.backend_dir.resolve()
        try:
            # 检查 base_path 是否在 backend 目录内
            resolved_base.relative_to(resolved_backend)
            # 如果没抛异常，说明 base_path 在 backend 内，禁止
            raise ValueError(
                f"安全检查失败：存储路径 {self.base_path} 在 backend 目录 {self.backend_dir} 内。"
                "请设置环境变量 LOCAL_STORAGE_PATH 为 backend 目录之外的路径，或设置为相对路径如 'tasks'。"
            )
        except ValueError as e:
            # 检查是否是上面的主动抛出（禁止），还是真的在外（允许）
            if "安全检查失败" in str(e):
                raise
            # ValueError 说明 base_path 不在 backend 内，验证通过
            pass

    def _safe_path(self, folder: str, filename: str) -> Path:
        """生成安全的目标路径"""
        folder_path = self.base_path / folder
        file_path = folder_path / filename
        resolved_file = file_path.resolve()
        resolved_backend = self.backend_dir.resolve()
        try:
            resolved_file.relative_to(resolved_backend)
            raise ValueError(
                f"安全检查失败：文件路径 {file_path} 在 backend 目录内。"
                f"文件必须保存在 {self.base_path}。"
            )
        except ValueError:
            pass
        return file_path

    def _is_safe_path(self, path: Path) -> bool:
        """检查路径是否安全（不在 backend 内）"""
        try:
            path.resolve().relative_to(self.backend_dir.resolve())
            return False
        except ValueError:
            return True

    def init_task_path(self, project_name: Optional[str] = None) -> str:
        """
        为新会话/任务初始化存储路径

        Args:
            project_name: 项目名称，如果提供则用 <项目名>_<时间戳> 格式

        Returns:
            相对路径字符串，格式如 "flask_blog_1742644800000"
        """
        timestamp = int(time.time() * 1000)
        if project_name:
            # 清理项目名称，只保留合法字符
            safe_name = self._sanitize_project_name(project_name)
            folder_name = f"{safe_name}_{timestamp}"
        else:
            folder_name = f"task_{timestamp}"

        folder_path = self.base_path / folder_name
        if not self._is_safe_path(folder_path):
            raise ValueError(f"安全检查失败：项目路径 {folder_path} 在 backend 目录内")

        folder_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[LocalStorage] 初始化任务路径: {folder_path}")
        return folder_name

    def get_task_path(self, folder_name: str) -> Path:
        """获取指定任务文件夹的绝对路径"""
        return self.base_path / folder_name

    def _sanitize_project_name(self, name: str) -> str:
        """清理项目名称，只保留合法字符"""
        import re
        # 只保留字母、数字、下划线、连字符
        safe = re.sub(r'[^\w\-]', '_', name)
        # 多个下划线合并为一个
        safe = re.sub(r'_+', '_', safe)
        # 去除首尾的下划线和连字符
        safe = safe.strip('_-')
        return safe or "project"

    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = "",
        project_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """上传文件到本地"""
        try:
            if project_name and not folder:
                folder = self.init_task_path(project_name)

            if not folder:
                return {"success": False, "error": "folder 不能为空"}

            file_path = self._safe_path(folder, filename)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            ext = Path(filename).suffix
            unique_name = f"{uuid.uuid4().hex}{ext}"
            final_path = file_path.parent / unique_name

            async with aiofiles.open(final_path, "wb") as f:
                await f.write(file_data)

            return {
                "success": True,
                "key": str(final_path.relative_to(self.base_path)),
                "url": f"/storage/{folder}/{unique_name}",
                "project_folder": folder,
            }
        except ValueError as e:
            logger.error(f"[LocalStorage] 安全检查失败: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[LocalStorage] 上传失败: {e}")
            return {"success": False, "error": str(e)}

    async def write_file(
        self,
        content: str,
        filename: str,
        folder: str
    ) -> Dict[str, Any]:
        """直接写入文本文件内容（供 code_generator 等调用）

        Args:
            content: 文件内容
            filename: 文件名
            folder: 文件夹名（相对路径）

        Returns:
            包含 success、path、url 等字段的字典
        """
        try:
            file_path = self._safe_path(folder, filename)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(f"[LocalStorage] 写入文件: {file_path}")
            return {
                "success": True,
                "path": str(file_path),
                "relative_path": str(file_path.relative_to(self.base_path)),
                "url": f"/storage/{folder}/{filename}",
                "project_folder": folder,
            }
        except ValueError as e:
            logger.error(f"[LocalStorage] 安全检查失败: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[LocalStorage] 写入失败: {e}")
            return {"success": False, "error": str(e)}

    async def download(self, key: str) -> Optional[bytes]:
        """下载文件"""
        try:
            file_path = self.base_path / key
            if file_path.exists():
                async with aiofiles.open(file_path, "rb") as f:
                    return await f.read()
            return None
        except Exception:
            return None

    async def delete(self, key: str) -> bool:
        """删除文件"""
        try:
            file_path = self.base_path / key
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception:
            return False

    async def get_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """获取访问 URL"""
        return f"/storage/{key}"

    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        try:
            folder_path = self.base_path / prefix
            if not folder_path.exists():
                return []

            files = []
            for i, file_path in enumerate(folder_path.rglob("*")):
                if file_path.is_file() and i < max_keys:
                    files.append({
                        "key": str(file_path.relative_to(self.base_path)),
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                    })
            return files
        except Exception:
            return []

    async def build_file_tree(self, folder_name: str) -> List[Dict[str, Any]]:
        """构建指定任务目录的文件树结构

        Args:
            folder_name: 任务文件夹名（如 "flask_blog_1742644800000"）

        Returns:
            文件树列表，格式如 [{name, path, type, children}]
        """
        folder_path = self.base_path / folder_name
        if not folder_path.exists():
            return []

        return self._build_tree_recursive(folder_path, folder_path)

    def _build_tree_recursive(self, base: Path, current: Path) -> List[Dict[str, Any]]:
        """递归构建文件树"""
        result = []
        try:
            for item in sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                if item.name.startswith('.'):
                    continue
                relative = str(item.relative_to(base))
                node = {
                    "name": item.name,
                    "path": relative,
                    "type": "directory" if item.is_dir() else "file",
                }
                if item.is_dir():
                    children = self._build_tree_recursive(base, item)
                    node["children"] = children
                result.append(node)
        except PermissionError:
            pass
        return result
