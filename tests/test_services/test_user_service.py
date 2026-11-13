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
        """测试获取用户（现契约：需要 db 注入，2026-11-13 黄金集对齐）"""
        from app.services.user import UserService

        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = None
        db = MagicMock()
        db.execute = AsyncMock(return_value=fake_result)
        service = UserService(db=db)
        user = await service.get_user("test-user-id")
        assert user is None

    @pytest.mark.asyncio
    async def test_create_user(self):
        """测试创建用户（现契约：接收 UserCreate、返回 User 模型）"""
        from app.services.user import UserService
        from app.schemas.user import UserCreate

        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        service = UserService(db=db)
        result = await service.create_user(UserCreate(
            username="testuser",
            email="test@example.com",
            password="password123",
        ))
        assert result.username == "testuser"
        assert result.hashed_password != "password123"
        db.add.assert_called_once()
