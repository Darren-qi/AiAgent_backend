"""企业微信机器人"""

from typing import Dict, Any, Optional
import httpx


class WeComBot:
    """企业微信机器人"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret

    async def send_text(self, content: str, mentioned_list: Optional[list] = None) -> bool:
        """发送文本消息"""
        msg = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_list or [],
            },
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=msg)
            return response.status_code == 200

    async def send_markdown(self, content: str) -> bool:
        """发送 Markdown 消息"""
        msg = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=msg)
            return response.status_code == 200

    async def send_image(self, media_id: str) -> bool:
        """发送图片消息"""
        msg = {
            "msgtype": "image",
            "image": {"media_id": media_id},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=msg)
            return response.status_code == 200

    async def send_news(self, articles: list) -> bool:
        """发送图文消息"""
        msg = {
            "msgtype": "news",
            "news": {"articles": articles},
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.webhook_url, json=msg)
            return response.status_code == 200
