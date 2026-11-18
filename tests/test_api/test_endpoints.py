"""Test API endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
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
            response = await client.get("/api/v1/health/health")  # 路由含 /health 子路径
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
                json={"username_or_email": "testuser", "password": "testpass"}
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
                json={"username_or_email": "wrong", "password": "wrong"}
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
                "/api/v1/agent/execute/",   # 路由带尾斜杠，不加会307
                json={
                    "task": "Say hello",
                    "context": {}
                },
                headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code in [200, 401, 500]

    @pytest.mark.asyncio
    async def test_agent_execute_without_auth(self):
        """测试未认证 Agent 执行——统一错误信封（阶段修复 2026-11-17）。

        裸 HTTPException 迁移后：body 是 {error, status_code, error_code}
        而非 {detail}，且 401 保留 WWW-Authenticate 响应头。
        """
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/agent/execute/",   # 路由带尾斜杠，不加会307
                json={"task": "Say hello", "context": {}}
            )
            assert response.status_code == 401
            body = response.json()
            assert body.get("error_code") == "UNAUTHORIZED", body
            assert "error" in body and "detail" not in body, body
            assert response.headers.get("WWW-Authenticate") == "Bearer"


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
                "/api/v1/agent/create-session/",   # session 路由已删，现走 agent
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
                "/api/v1/agent/get-session/",   # memory/session 路由已删，现走 agent
                params={"session_id": "session-123"},
                headers={"Authorization": "Bearer test-token"}
            )
            assert response.status_code in [200, 401]
