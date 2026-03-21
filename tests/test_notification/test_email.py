"""Test Notification services."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestEmailNotifier:
    """Test email notifier"""

    def test_create_email_notifier(self):
        """测试创建邮件通知器"""
        from app.notification.email import EmailNotifier

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_address="user@example.com"
        )
        assert notifier is not None

    @pytest.mark.asyncio
    async def test_send_email(self):
        """测试发送邮件"""
        from app.notification.email import EmailNotifier

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_address="user@example.com"
        )
        result = await notifier.send(
            to_addresses=["test@example.com"],
            subject="Test Email",
            content="This is a test email"
        )
        assert isinstance(result, dict)
