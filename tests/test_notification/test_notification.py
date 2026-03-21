"""Notification 测试"""

import pytest
from app.agent.tools.notification.manager import NotificationManager


class TestNotificationManager:
    """通知管理器测试"""

    def test_create_manager(self):
        """测试创建管理器"""
        manager = NotificationManager()
        assert manager is not None

    @pytest.mark.asyncio
    async def test_send_email_disabled(self):
        """测试邮件发送未启用"""
        manager = NotificationManager()
        manager.email_enabled = False
        result = await manager.send_email(
            to=["test@example.com"],
            subject="Test",
            content="Test content"
        )
        assert result.success is False
        assert "未启用" in result.error

    @pytest.mark.asyncio
    async def test_send_scheduled_notification(self):
        """测试定时任务通知"""
        manager = NotificationManager()
        results = await manager.send_scheduled_notification(
            task_name="test_task",
            status="completed",
            result="Task completed successfully",
            channels=["email"]
        )
        assert isinstance(results, dict)
