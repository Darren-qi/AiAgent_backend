"""
用户接口测试

测试用户 CURD 操作。
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.user import User


class TestUsers:
    """用户接口测试类"""

    @pytest.mark.asyncio
    async def test_update_current_user(
        self, client: AsyncClient, test_user: User
    ):
        """测试更新当前用户信息"""
        token = create_access_token(str(test_user.id))

        response = await client.patch(
            "/api/v1/users/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "nickname": "Updated Nickname",
                "bio": "This is my new bio",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["nickname"] == "Updated Nickname"
        assert data["bio"] == "This is my new bio"

    @pytest.mark.asyncio
    async def test_change_password_success(
        self, client: AsyncClient, test_user: User
    ):
        """测试修改密码成功"""
        token = create_access_token(str(test_user.id))

        response = await client.patch(
            "/api/v1/users/profile/password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "old_password": "password123",
                "new_password": "newpassword456",
            },
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_change_password_wrong_old(
        self, client: AsyncClient, test_user: User
    ):
        """测试旧密码错误"""
        token = create_access_token(str(test_user.id))

        response = await client.patch(
            "/api/v1/users/profile/password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "old_password": "wrongpassword",
                "new_password": "newpassword456",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_get_users(
        self, client: AsyncClient, test_user: User, admin_user: User
    ):
        """测试管理员获取用户列表"""
        admin_token = create_access_token(str(admin_user.id))

        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "meta" in data
        assert len(data["items"]) >= 2  # 至少包含 test_user 和 admin_user

    @pytest.mark.asyncio
    async def test_normal_user_cannot_get_users(
        self, client: AsyncClient, test_user: User
    ):
        """测试普通用户不能获取用户列表"""
        token = create_access_token(str(test_user.id))

        response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_update_user(
        self, client: AsyncClient, test_user: User, admin_user: User
    ):
        """测试管理员更新用户"""
        admin_token = create_access_token(str(admin_user.id))

        response = await client.patch(
            f"/api/v1/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "status": "banned",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "banned"

    @pytest.mark.asyncio
    async def test_admin_delete_user(
        self, client: AsyncClient, test_user: User, admin_user: User
    ):
        """测试管理员删除用户"""
        admin_token = create_access_token(str(admin_user.id))

        response = await client.delete(
            f"/api/v1/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_cannot_delete_self(
        self, client: AsyncClient, admin_user: User
    ):
        """测试管理员不能删除自己"""
        admin_token = create_access_token(str(admin_user.id))

        response = await client.delete(
            f"/api/v1/users/{admin_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 400
