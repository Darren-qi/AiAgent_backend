"""存储提供商基类"""

import builtins
from abc import ABC, abstractmethod
from typing import Any


class BaseStorageProvider(ABC):
    """存储提供商基类"""

    @abstractmethod
    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: str | None = None,
        folder: str = ""
    ) -> dict[str, Any]:
        """上传文件"""
        pass

    @abstractmethod
    async def download(self, key: str) -> bytes | None:
        """下载文件"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除文件"""
        pass

    @abstractmethod
    async def get_url(self, key: str, expires: int = 3600) -> str | None:
        """获取访问 URL"""
        pass

    @abstractmethod
    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        pass

    @abstractmethod
    async def write_file(self, content: str, filename: str, folder: str) -> dict[str, Any]:
        """直接写入文本文件"""
        pass

    @abstractmethod
    async def build_file_tree(self, folder_name: str) -> builtins.list[dict[str, Any]]:
        """构建文件树"""
        pass
