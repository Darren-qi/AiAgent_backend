"""
认证接口测试

测试用户注册、登录、登出等功能。
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token


class TestAuth:
    """认证接口测试类"""

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        """测试成功注册"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "password123",
                "nickname": "New User",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client: AsyncClient, test_user):
        """测试用户名重复注册"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "testuser",  # 与 test_user 重复
                "email": "another@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, test_user):
        """测试邮箱重复注册"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "anotheruser",
                "email": "test@example.com",  # 与 test_user 重复
                "password": "password123",
            },
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """测试无效邮箱格式"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "invalid-email",
                "password": "password123",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_short_password(self, client: AsyncClient):
        """测试密码过短"""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "short",  # 少于 8 字符
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_user):
        """测试成功登录"""
        response = await client.post(
            f"/api/v1/auth/login?username_or_email={test_user.username}&password=password123",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """测试密码错误"""
        response = await client.post(
            f"/api/v1/auth/login?username_or_email={test_user.username}&password=wrongpassword",
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """测试用户不存在"""
        response = await client.post(
            "/api/v1/auth/login?username_or_email=nonexistent&password=password123",
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_get_current_user(self, client: AsyncClient, test_user):
        """测试获取当前用户信息"""
        # 先生成访问令牌
        token = create_access_token(str(test_user.id))

        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == test_user.username
        assert data["email"] == test_user.email

    @pytest.mark.asyncio
    async def test_get_current_user_no_token(self, client: AsyncClient):
        """测试无令牌访问"""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self, client: AsyncClient):
        """测试无效令牌访问"""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

        assert response.status_code == 401
