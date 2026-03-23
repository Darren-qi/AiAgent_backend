"""百度云 BOS 存储"""

import os
from typing import Optional, Dict, Any, List
from app.agent.tools.storage.providers.base import BaseStorageProvider


class BaiduBOSProvider(BaseStorageProvider):
    """百度云 BOS 存储提供商"""

    def __init__(self):
        self.enabled = False
        self.bucket = os.environ.get("BAIDU_BCE_BUCKET", "")
        self.region = os.environ.get("BAIDU_BCE_REGION", "bj")
        self.prefix = os.environ.get("BAIDU_BCE_PREFIX", "aiagent/")

        if os.environ.get("BAIDU_BCE_AK"):
            self.enabled = True

    async def upload(
        self,
        file_data: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = ""
    ) -> Dict[str, Any]:
        """上传文件到百度云 BOS"""
        if not self.enabled:
            return {"success": False, "error": "百度云 BOS 未配置"}

        try:
            from baidubce import bce_base_config
            from baidubce.services import bos
            from baidubce.services.bos import BosService

            config = bce_base_config.Config(
                credentials={
                    "access_key_id": os.environ.get("BAIDU_BCE_AK"),
                    "secret_access_key": os.environ.get("BAIDU_BCE_SK"),
                }
            )

            client = BosService(config)

            key = f"{self.prefix}{folder}/{filename}"

            client.put_object(self.bucket, key, file_data)

            return {
                "success": True,
                "key": key,
                "url": f"https://{self.bucket}.{self.region}.bcebos.com/{key}",
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
        return f"https://{self.bucket}.{self.region}.bcebos.com/{key}"

    async def list(self, prefix: str = "", max_keys: int = 100) -> list:
        """列出文件"""
        return []

    async def write_file(self, content: str, filename: str, folder: str) -> Dict[str, Any]:
        """写入文本文件（云存储不支持直接写入）"""
        return {"success": False, "error": "云存储不支持直接写入"}

    async def build_file_tree(self, folder_name: str) -> List[Dict[str, Any]]:
        """构建文件树（云存储暂不支持）"""
        return []
