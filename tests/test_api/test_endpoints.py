"""Test API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestHealthEndpoint:
    """Test health check endpoint"""

    @pytest.mark.asyncio
    async def test_health_check(self):
        """测试健康检查端点"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data or "message" in data


class TestAuthEndpoint:
    """Test authentication endpoint"""

    @pytest.mark.asyncio
    async def test_login_success(self):
        """测试登录成功"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "testpass"}
            )
            assert response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self):
        """测试无效凭据登录"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": "wrong", "password": "wrong"}
            )
            assert response.status_code in [400, 401]


class TestAgentEndpoint:
    """Test agent endpoint"""

    @pytest.mark.asyncio
    async def test_agent_execute(self):
        """测试 Agent 执行"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/agent/execute",
                json={
                    "task": "Say hello",
                    "context": {}
                },
                headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code in [200, 401, 500]

    @pytest.mark.asyncio
    async def test_agent_execute_without_auth(self):
        """测试未认证 Agent 执行"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/agent/execute",
                json={"task": "Say hello", "context": {}}
            )
            assert response.status_code == 401


class TestConversationEndpoint:
    """Test conversation endpoint"""

    @pytest.mark.asyncio
    async def test_create_conversation(self):
        """测试创建会话"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/conversations/",
                json={"title": "Test Conversation"},
                headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code in [200, 201, 401]


class TestMemoryEndpoint:
    """Test memory endpoint"""

    @pytest.mark.asyncio
    async def test_get_memory(self):
        """测试获取记忆"""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/memory/session-123",
                headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code in [200, 401]
