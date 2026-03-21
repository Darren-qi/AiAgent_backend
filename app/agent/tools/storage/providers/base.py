"""存储提供商基类"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseStorageProvider(ABC):
    """存储提供商基类"""

    @abstractmethod
    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> Dict[str, Any]:
        """上传文件"""
        pass

    @abstractmethod
    async def download(self, key: str) -> Optional[bytes]:
        """下载文件"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除文件"""
        pass

    @abstractmethod
    async def get_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """获取访问 URL"""
        pass

    @abstractmethod
    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        pass
