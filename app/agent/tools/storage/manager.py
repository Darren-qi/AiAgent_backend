"""存储管理器 - 统一管理多种对象存储"""

import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class StorageProvider(str, Enum):
    """存储提供商"""
    TENCENT = "tencent"
    ALIYUN = "aliyun"
    BAIDU = "baidu"
    MINIO = "minio"
    LOCAL = "local"


@dataclass
class StorageResult:
    """存储结果"""
    success: bool
    url: Optional[str] = None
    key: Optional[str] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class StorageManager:
    """对象存储管理器"""

    def __init__(self):
        self.provider_name = os.environ.get("STORAGE_PROVIDER", "local").lower()
        self._provider = self._create_provider()

    def _create_provider(self) -> Any:
        """创建存储提供商实例"""
        from app.agent.tools.storage.providers.tencent import TencentCOSProvider
        from app.agent.tools.storage.providers.aliyun import AliyunOSSProvider
        from app.agent.tools.storage.providers.baidu import BaiduBOSProvider
        from app.agent.tools.storage.providers.minio import MinIOProvider
        from app.agent.tools.storage.providers.local import LocalStorageProvider

        providers = {
            StorageProvider.TENCENT: TencentCOSProvider,
            StorageProvider.ALIYUN: AliyunOSSProvider,
            StorageProvider.BAIDU: BaiduBOSProvider,
            StorageProvider.MINIO: MinIOProvider,
            StorageProvider.LOCAL: LocalStorageProvider,
        }

        provider_class = providers.get(StorageProvider(self.provider_name), LocalStorageProvider)
        return provider_class()

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> StorageResult:
        """上传文件"""
        return await self._provider.upload(file_data, filename, content_type, folder)

    async def download_file(self, key: str) -> Optional[bytes]:
        """下载文件"""
        return await self._provider.download(key)

    async def delete_file(self, key: str) -> bool:
        """删除文件"""
        return await self._provider.delete(key)

    async def get_file_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """获取文件访问 URL"""
        return await self._provider.get_url(key, expires)

    async def list_files(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        return await self._provider.list(prefix, max_keys)
