"""飞书 (Lark) 机器人"""

from typing import Dict, Any, Optional
import httpx


class FeishuBot:
    """飞书机器人"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.access_token: Optional[str] = None

    async def get_access_token(self) -> str:
        """获取访问令牌"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = response.json()
            self.access_token = data.get("tenant_access_token", "")
            return self.access_token

    async def send_message(self, receive_id: str, msg_type: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """发送消息"""
        token = self.access_token or await self.get_access_token()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "receive_id": receive_id,
                    "msg_type": msg_type,
                    "content": content,
                },
            )
            return response.json()

    async def send_text(self, receive_id: str, text: str) -> Dict[str, Any]:
        """发送文本消息"""
        return await self.send_message(receive_id, "text", {"text": text})

    async def create_webhook(self, name: str, webhook_url: str) -> Dict[str, Any]:
        """创建自定义机器人 webhook"""
        return {"success": True, "webhook_url": webhook_url}

    async def send_webhook_message(self, webhook_url: str, msg: Dict[str, Any]) -> bool:
        """通过 webhook 发送消息"""
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=msg)
            return response.status_code == 200
