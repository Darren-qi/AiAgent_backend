"""Test Social platform integrations."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestFeishuBot:
    """Test Feishu bot"""

    def test_create_feishu_bot(self):
        """测试创建飞书机器人"""
        from app.social.feishu.bot import FeishuBot

        bot = FeishuBot(app_id="test-id", app_secret="test-secret")
        assert bot is not None


class TestWeComBot:
    """Test WeCom bot"""

    def test_create_wecom_bot(self):
        """测试创建企业微信机器人"""
        from app.social.wecom.bot import WeComBot

        bot = WeComBot(webhook_url="https://example.com/webhook")
        assert bot is not None
