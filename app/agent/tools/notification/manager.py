"""通知管理器"""

import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class NotificationResult:
    """通知结果"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class NotificationManager:
    """通知管理器 - 统一管理所有通知渠道"""

    def __init__(self):
        self.email_enabled = os.environ.get("EMAIL_NOTIFICATION_ENABLED", "false").lower() == "true"
        self.social_enabled = True

    async def send_email(
        self,
        to: List[str],
        subject: str,
        content: str,
        html: bool = False,
        attachments: Optional[List[Dict[str, bytes]]] = None
    ) -> NotificationResult:
        """发送邮件通知"""
        if not self.email_enabled:
            return NotificationResult(success=False, error="邮件通知未启用")

        try:
            from app.agent.tools.notification.email.smtp import EmailSender
            sender = EmailSender()
            message_id = await sender.send(
                to=to,
                subject=subject,
                content=content,
                html=html,
                attachments=attachments
            )
            return NotificationResult(success=True, message_id=message_id)
        except Exception as e:
            return NotificationResult(success=False, error=str(e))

    async def send_to_social(
        self,
        provider: str,
        chat_id: str,
        content: str,
        notification_type: str = "text"
    ) -> NotificationResult:
        """发送社交平台通知"""
        try:
            from app.agent.tools.social.manager import SocialManager
            manager = SocialManager()
            return await manager.send_message(provider, chat_id, content)
        except Exception as e:
            return NotificationResult(success=False, error=str(e))

    async def send_broadcast(
        self,
        channels: List[str],
        recipients: Dict[str, List[str]],
        subject: str,
        content: str
    ) -> Dict[str, NotificationResult]:
        """广播通知到多个渠道"""
        results = {}

        if "email" in channels:
            email_recipients = recipients.get("email", [])
            if email_recipients:
                results["email"] = await self.send_email(
                    to=email_recipients,
                    subject=subject,
                    content=content
                )

        social_channels = ["feishu", "wecom", "dingtalk", "telegram"]
        for channel in channels:
            if channel in social_channels:
                social_recipients = recipients.get(channel, [])
                for recipient in social_recipients:
                    results[f"{channel}_{recipient}"] = await self.send_to_social(
                        provider=channel,
                        chat_id=recipient,
                        content=f"{subject}\n\n{content}"
                    )

        return results

    async def send_scheduled_notification(
        self,
        task_name: str,
        status: str,
        result: str,
        notify_channels: List[str]
    ) -> Dict[str, NotificationResult]:
        """发送定时任务通知"""
        subject = f"[{status}] 定时任务 - {task_name}"
        content = f"任务状态: {status}\n\n结果:\n{result}"

        recipients = {"email": os.environ.get("EMAIL_NOTIFICATION_RECIPIENTS", "").split(",")}

        return await self.send_broadcast(
            channels=notify_channels,
            recipients=recipients,
            subject=subject,
            content=content
        )

    async def send(
        self,
        channel: str = "email",
        recipient: str = "",
        title: str = "AiAgent 通知",
        content: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        统一的发送接口（供 NotificationSkill 调用）

        Args:
            channel: 通知渠道
            recipient: 接收人/地址
            title: 通知标题
            content: 通知内容

        Returns:
            发送结果字典
        """
        if channel == "email":
            email_result = await self.send_email(
                to=[recipient] if recipient else os.environ.get("EMAIL_NOTIFICATION_RECIPIENTS", "").split(","),
                subject=title,
                content=content,
                html=kwargs.get("html", False)
            )
            return {
                "success": email_result.success,
                "notification_id": email_result.message_id,
                "error": email_result.error
            }
        elif channel in ["feishu", "wecom", "dingtalk", "telegram"]:
            social_result = await self.send_to_social(
                provider=channel,
                chat_id=recipient or "default",
                content=f"{title}\n\n{content}"
            )
            return {
                "success": social_result.success,
                "notification_id": social_result.message_id,
                "error": social_result.error
            }
        else:
            return {
                "success": False,
                "error": f"不支持的通知渠道: {channel}"
            }
