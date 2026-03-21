"""企业微信客户端"""

import os
import httpx
from typing import Optional


class WeComClient:
    """企业微信客户端"""

    def __init__(self):
        self.corp_id = os.environ.get("WECOM_CORP_ID", "")
        self.corp_secret = os.environ.get("WECOM_CORP_SECRET", "")
        self.agent_id = os.environ.get("WECOM_AGENT_ID", "")
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self._access_token:
            return self._access_token

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {
            "corpid": self.corp_id,
            "corpsecret": self.corp_secret,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            data = response.json()
            if data.get("errcode") != 0:
                raise Exception(f"企业微信获取 Token 错误: {data.get('errmsg')}")
            self._access_token = data.get("access_token", "")
            return self._access_token

    async def send_text(self, chat_id: str, content: str) -> str:
        """发送文本消息"""
        token = await self._get_access_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                params={"access_token": token},
                json={
                    "touser": chat_id,
                    "msgtype": "text",
                    "agentid": self.agent_id,
                    "text": {"content": content},
                }
            )
            data = response.json()
            if data.get("errcode") != 0:
                raise Exception(f"企业微信发送消息错误: {data.get('errmsg')}")
            return str(data.get("msgid", ""))

    async def send_image(self, chat_id: str, media_id: str) -> str:
        """发送图片消息"""
        token = await self._get_access_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                params={"access_token": token},
                json={
                    "touser": chat_id,
                    "msgtype": "image",
                    "agentid": self.agent_id,
                    "image": {"media_id": media_id},
                }
            )
            data = response.json()
            if data.get("errcode") != 0:
                raise Exception(f"企业微信发送图片错误: {data.get('errmsg')}")
            return str(data.get("msgid", ""))

    async def upload_media(self, file_data: bytes, file_type: str = "image") -> str:
        """上传临时素材"""
        token = await self._get_access_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/media/upload"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                params={"access_token": token, "type": file_type},
                files={"media": ("file.png", file_data, "image/png")},
            )
            data = response.json()
            if data.get("errcode") != 0:
                raise Exception(f"企业微信上传素材错误: {data.get('errmsg')}")
            return data.get("media_id", "")

    async def send_webhook(self, webhook_url: str, content: str) -> bool:
        """发送 Webhook 消息"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json={
                    "msgtype": "text",
                    "text": {"content": content},
                }
            )
            data = response.json()
            return data.get("errcode") == 0
