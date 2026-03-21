"""MinIO 存储"""

import os
from typing import Optional, Dict, Any
from app.agent.tools.storage.providers.base import BaseStorageProvider


class MinIOProvider(BaseStorageProvider):
    """MinIO 存储提供商"""

    def __init__(self):
        self.enabled = False
        self.endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        self.bucket = os.environ.get("MINIO_BUCKET", "aiagent")
        self.secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"

        if os.environ.get("MINIO_ACCESS_KEY"):
            self.enabled = True

    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> Dict[str, Any]:
        """上传文件到 MinIO"""
        if not self.enabled:
            return {"success": False, "error": "MinIO 未配置"}

        try:
            from minio import Minio

            client = Minio(
                self.endpoint,
                access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
                secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
                secure=self.secure
            )

            key = f"{folder}/{filename}" if folder else filename

            data = file_data
            client.put_object(
                self.bucket,
                key,
                data,
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )

            url = f"{'https' if self.secure else 'http'}://{self.endpoint}/{self.bucket}/{key}"

            return {
                "success": True,
                "key": key,
                "url": url,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def download(self, key: str) -> Optional[bytes]:
        """下载文件"""
        if not self.enabled:
            return None
        return None

    async def delete(self, key: str) -> bool:
        """删除文件"""
        if not self.enabled:
            return False
        return True

    async def get_url(self, key: str, expires: int = 3600) -> Optional[str]:
        """获取访问 URL"""
        return f"{'https' if self.secure else 'http'}://{self.endpoint}/{self.bucket}/{key}"

    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        return []
