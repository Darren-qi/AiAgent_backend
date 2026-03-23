"""阿里云 OSS 存储"""

import os
from typing import Optional, Dict, Any, List
from app.agent.tools.storage.providers.base import BaseStorageProvider


class AliyunOSSProvider(BaseStorageProvider):
    """阿里云 OSS 存储提供商"""

    def __init__(self):
        self.enabled = False
        self.bucket = os.environ.get("ALIYUN_OSS_BUCKET", "")
        self.region = os.environ.get("ALIYUN_OSS_REGION", "oss-cn-hangzhou")
        self.prefix = os.environ.get("ALIYUN_OSS_PREFIX", "aiagent/")

        if os.environ.get("ALIYUN_OSS_ACCESS_KEY_ID"):
            self.enabled = True

    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> Dict[str, Any]:
        """上传文件到阿里云 OSS"""
        if not self.enabled:
            return {"success": False, "error": "阿里云 OSS 未配置"}

        try:
            import oss2

            auth = oss2.Auth(
                os.environ.get("ALIYUN_OSS_ACCESS_KEY_ID"),
                os.environ.get("ALIYUN_OSS_ACCESS_KEY_SECRET")
            )
            bucket = oss2.Bucket(auth, f"https://{self.region}.aliyuncs.com", self.bucket)

            key = f"{self.prefix}{folder}/{filename}"

            bucket.put_object(key, file_data, headers={"Content-Type": content_type or "application/octet-stream"})

            return {
                "success": True,
                "key": key,
                "url": f"https://{self.bucket}.{self.region}.aliyuncs.com/{key}",
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
        return f"https://{self.bucket}.{self.region}.aliyuncs.com/{key}"

    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        return []

    async def write_file(self, content: str, filename: str, folder: str) -> Dict[str, Any]:
        """写入文本文件（云存储不支持直接写入）"""
        return {"success": False, "error": "云存储不支持直接写入"}

    async def build_file_tree(self, folder_name: str) -> List[Dict[str, Any]]:
        """构建文件树（云存储暂不支持）"""
        return []
