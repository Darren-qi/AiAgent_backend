"""Social 模块测试"""

import pytest
from app.agent.tools.social.manager import SocialManager, SocialProvider


class TestSocialManager:
    """社交管理器测试"""

    def test_create_manager(self):
        """测试创建管理器"""
        manager = SocialManager()
        assert manager is not None
        assert isinstance(manager.providers, dict)

    def test_get_available_providers(self):
        """测试获取可用提供商"""
        manager = SocialManager()
        providers = manager.get_available_providers()
        assert isinstance(providers, list)

    @pytest.mark.asyncio
    async def test_send_message_no_provider(self):
        """测试发送消息到未配置的平台"""
        manager = SocialManager()
        result = await manager.send_message(
            provider="nonexistent",
            chat_id="test",
            content="test"
        )
        assert result.success is False
        assert result.error is not None
