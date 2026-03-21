"""本地存储"""

import os
import uuid
import aiofiles
from pathlib import Path
from typing import Optional, Dict, Any
from app.agent.tools.storage.providers.base import BaseStorageProvider


class LocalStorageProvider(BaseStorageProvider):
    """本地文件系统存储"""

    def __init__(self):
        self.base_path = Path(os.environ.get("LOCAL_STORAGE_PATH", "./uploads"))
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> Dict[str, Any]:
        """上传文件到本地"""
        try:
            folder_path = self.base_path / folder
            folder_path.mkdir(parents=True, exist_ok=True)

            ext = Path(filename).suffix
            unique_name = f"{uuid.uuid4().hex}{ext}"
            file_path = folder_path / unique_name

            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_data)

            return {
                "success": True,
                "key": str(file_path.relative_to(self.base_path)),
                "url": f"/storage/{folder}/{unique_name}",
            }
        except Exception as e:
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
