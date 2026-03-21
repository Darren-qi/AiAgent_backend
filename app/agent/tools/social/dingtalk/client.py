"""钉钉客户端"""

import os
import httpx
from typing import Optional


class DingTalkClient:
    """钉钉客户端"""

    def __init__(self):
        self.app_key = os.environ.get("DINGTALK_APP_KEY", "")
        self.app_secret = os.environ.get("DINGTALK_APP_SECRET", "")
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        if self._access_token:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "appKey": self.app_key,
                "appSecret": self.app_secret,
            })
            data = response.json()
            if data.get("errCode") != 0:
                raise Exception(f"钉钉获取 Token 错误: {data.get('errMsg')}")
            self._access_token = data.get("accessToken", "")
            return self._access_token

    async def send_text(self, chat_id: str, content: str) -> str:
        """发送文本消息"""
        token = await self._get_access_token()
        url = "https://api.dingtalk.com/v1.0/im/messages"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "chatbotCorpId": chat_id,
                    "msgMap": {
                        "text": {"content": content},
                    },
                    "msgType": "text",
                }
            )
            data = response.json()
            if data.get("errCode") != 0:
                raise Exception(f"钉钉发送消息错误: {data.get('errMsg')}")
            return data.get("processQueryKey", "")

    async def send_image(self, chat_id: str, image_key: str) -> str:
        """发送图片消息"""
        token = await self._get_access_token()
        url = "https://api.dingtalk.com/v1.0/im/messages"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "chatbotCorpId": chat_id,
                    "msgMap": {
                        "image": {"imageKey": image_key},
                    },
                    "msgType": "image",
                }
            )
            data = response.json()
            if data.get("errCode") != 0:
                raise Exception(f"钉钉发送图片错误: {data.get('errMsg')}")
            return data.get("processQueryKey", "")

    async def send_markdown(self, chat_id: str, title: str, content: str) -> str:
        """发送 Markdown 消息"""
        token = await self._get_access_token()
        url = "https://api.dingtalk.com/v1.0/im/messages"

        markdown_content = f"# {title}\n\n{content}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"x-acs-dingtalk-access-token": token},
                json={
                    "chatbotCorpId": chat_id,
                    "msgMap": {
                        "markdown": {"title": title, "text": markdown_content},
                    },
                    "msgType": "markdown",
                }
            )
            data = response.json()
            if data.get("errCode") != 0:
                raise Exception(f"钉钉发送 Markdown 错误: {data.get('errMsg')}")
            return data.get("processQueryKey", "")
