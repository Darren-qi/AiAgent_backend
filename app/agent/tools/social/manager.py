"""社交管理器"""

import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class SocialProvider(str, Enum):
    """社交平台提供商"""
    FEISHU = "feishu"
    WECOM = "wecom"
    DINGTALK = "dingtalk"
    TELEGRAM = "telegram"


@dataclass
class MessageResult:
    """消息发送结果"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class SocialManager:
    """社交平台管理器"""

    def __init__(self):
        self.providers: Dict[str, Any] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        """初始化所有提供商"""
        from app.agent.tools.social.feishu.client import FeishuClient
        from app.agent.tools.social.wecom.client import WeComClient
        from app.agent.tools.social.dingtalk.client import DingTalkClient
        from app.agent.tools.social.telegram.bot import TelegramBot

        if os.environ.get("FEISHU_APP_ID"):
            self.providers["feishu"] = FeishuClient()

        if os.environ.get("WECOM_CORP_ID"):
            self.providers["wecom"] = WeComClient()

        if os.environ.get("DINGTALK_APP_KEY"):
            self.providers["dingtalk"] = DingTalkClient()

        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            self.providers["telegram"] = TelegramBot()

    async def send_message(
        self,
        provider: str,
        chat_id: str,
        content: str,
        msg_type: str = "text"
    ) -> MessageResult:
        """发送消息"""
        client = self.providers.get(provider)
        if not client:
            return MessageResult(success=False, error=f"未配置的社交平台: {provider}")

        try:
            if provider == "feishu":
                result = await client.send_text(chat_id, content)
            elif provider == "wecom":
                result = await client.send_text(chat_id, content)
            elif provider == "dingtalk":
                result = await client.send_text(chat_id, content)
            elif provider == "telegram":
                result = await client.send_message(int(chat_id), content)
            else:
                return MessageResult(success=False, error=f"不支持的提供商: {provider}")

            return MessageResult(success=True, message_id=result)
        except Exception as e:
            return MessageResult(success=False, error=str(e))

    async def send_image(
        self,
        provider: str,
        chat_id: str,
        image_url: str
    ) -> MessageResult:
        """发送图片"""
        client = self.providers.get(provider)
        if not client:
            return MessageResult(success=False, error=f"未配置的社交平台: {provider}")

        try:
            if provider == "feishu":
                result = await client.send_image(chat_id, image_url)
            elif provider == "wecom":
                result = await client.send_image(chat_id, image_url)
            elif provider == "dingtalk":
                result = await client.send_image(chat_id, image_url)
            else:
                return MessageResult(success=False, error=f"该平台不支持发送图片")

            return MessageResult(success=True, message_id=result)
        except Exception as e:
            return MessageResult(success=False, error=str(e))

    def get_available_providers(self) -> list:
        """获取已配置的提供商列表"""
        return list(self.providers.keys())
