"""Test services layer."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestUserService:
    """Test user service"""

    @pytest.mark.asyncio
    async def test_get_user(self):
        """测试获取用户"""
        from app.services.user import UserService

        service = UserService()
        user = await service.get_user("test-user-id")
        assert user is None or isinstance(user, dict)

    @pytest.mark.asyncio
    async def test_create_user(self):
        """测试创建用户"""
        from app.services.user import UserService

        service = UserService()
        result = await service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123"
        )
        assert isinstance(result, dict) or result is None
