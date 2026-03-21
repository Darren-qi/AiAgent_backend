"""内置 Skill - 通知发送"""

import logging
from typing import Dict, Any

from app.agent.skills.base import BaseSkill, SkillResult
from app.agent.tools.notification.manager import NotificationManager

logger = logging.getLogger(__name__)


class NotificationSkill(BaseSkill):
    """通知发送 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "notification"
        self.description = "发送通知（邮件、社交平台）"
        self.parameters = [
            {"name": "channel", "type": "string", "required": False, "description": "通知渠道: email/feishu/wecom/dingtalk"},
            {"name": "recipient", "type": "string", "required": False, "description": "接收人/接收地址"},
            {"name": "content", "type": "string", "required": True, "description": "通知内容"},
            {"name": "title", "type": "string", "required": False, "description": "通知标题"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        channel = kwargs.get("channel", "email")
        recipient = kwargs.get("recipient", "")
        content = kwargs.get("content", "")
        title = kwargs.get("title", "AiAgent 通知")

        if not content:
            return SkillResult(success=False, error="缺少 content 参数")

        try:
            notification_manager = NotificationManager()

            result = await notification_manager.send(
                channel=channel,
                recipient=recipient,
                title=title,
                content=content,
            )

            if result.get("success"):
                return SkillResult(
                    success=True,
                    data={"sent": True, "channel": channel, "recipient": recipient},
                    metadata={"notification_id": result.get("notification_id")}
                )
            else:
                return SkillResult(
                    success=False,
                    error=result.get("error", "发送失败")
                )
        except Exception as e:
            logger.error(f"[Notification] 发送通知失败: {e}")
            return SkillResult(success=False, error=str(e))
