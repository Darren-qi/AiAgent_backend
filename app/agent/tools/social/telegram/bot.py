"""Telegram Bot"""

import os
import httpx
from typing import Optional, List


class TelegramBot:
    """Telegram Bot"""

    def __init__(self):
        self.bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.allowed_users = self._parse_allowed_users()

    def _parse_allowed_users(self) -> List[int]:
        """解析允许的用户 ID"""
        users_str = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
        if not users_str:
            return []
        try:
            return [int(uid.strip()) for uid in users_str.split(",") if uid.strip()]
        except ValueError:
            return []

    def _check_user(self, user_id: int) -> bool:
        """检查用户是否有权限"""
        if not self.allowed_users:
            return True
        return user_id in self.allowed_users

    async def send_message(self, chat_id: int, text: str) -> str:
        """发送文本消息"""
        if not self._check_user(chat_id):
            raise Exception("用户未授权")

        url = f"{self.api_url}/sendMessage"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            })
            data = response.json()
            if not data.get("ok"):
                raise Exception(f"Telegram 发送消息错误: {data.get('description')}")
            return str(data.get("result", {}).get("message_id", ""))

    async def send_image(self, chat_id: int, image_url: str, caption: Optional[str] = None) -> str:
        """发送图片"""
        if not self._check_user(chat_id):
            raise Exception("用户未授权")

        url = f"{self.api_url}/sendPhoto"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "photo": image_url,
                "caption": caption,
            })
            data = response.json()
            if not data.get("ok"):
                raise Exception(f"Telegram 发送图片错误: {data.get('description')}")
            return str(data.get("result", {}).get("message_id", ""))

    async def get_updates(self, offset: int = 0, limit: int = 100) -> List[dict]:
        """获取更新"""
        url = f"{self.api_url}/getUpdates"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "offset": offset,
                "limit": limit,
            })
            data = response.json()
            if not data.get("ok"):
                return []
            return data.get("result", [])
