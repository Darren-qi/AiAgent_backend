"""飞书客户端"""

import os
import httpx
from typing import Optional, Dict, Any


class FeishuClient:
    """飞书客户端"""

    def __init__(self):
        self.app_id = os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        self.base_url = "https://open.feishu.cn/open-apis"
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self._access_token:
            return self._access_token

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            })
            data = response.json()
            self._access_token = data.get("tenant_access_token", "")
            return self._access_token

    async def send_text(self, chat_id: str, content: str) -> str:
        """发送文本消息"""
        token = await self._get_access_token()
        url = f"{self.base_url}/im/v1/messages?receive_id_type=chat_id"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": {"text": content},
                }
            )
            data = response.json()
            if data.get("code") != 0:
                raise Exception(f"飞书 API 错误: {data.get('msg')}")
            return data.get("data", {}).get("message_id", "")

    async def send_image(self, chat_id: str, image_key: str) -> str:
        """发送图片消息"""
        token = await self._get_access_token()
        url = f"{self.base_url}/im/v1/messages?receive_id_type=chat_id"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": chat_id,
                    "msg_type": "image",
                    "content": {"image_key": image_key},
                }
            )
            data = response.json()
            if data.get("code") != 0:
                raise Exception(f"飞书 API 错误: {data.get('msg')}")
            return data.get("data", {}).get("message_id", "")

    async def upload_image(self, image_data: bytes) -> str:
        """上传图片获取 image_key"""
        token = await self._get_access_token()
        url = f"{self.base_url}/im/v1/images"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                files={"image": ("image.png", image_data, "image/png")},
                data={"image_type": "message"},
            )
            data = response.json()
            if data.get("code") != 0:
                raise Exception(f"飞书上传图片错误: {data.get('msg')}")
            return data.get("data", {}).get("image_key", "")

    async def create_webhook(self, chat_id: str, name: str) -> str:
        """创建群机器人 Webhook"""
        token = await self._get_access_token()
        url = f"{self.base_url}/im/v1/chats/{chat_id}/managers"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"id": chat_id, "manager_type": "manager"},
            )
            return str(response.status_code)
