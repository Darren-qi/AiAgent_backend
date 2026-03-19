"""
文章接口测试

测试文章 CURD 操作。
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from app.models.user import User
from app.models.post import PostStatus


class TestPosts:
    """文章接口测试类"""

    @pytest.mark.asyncio
    async def test_create_post(
        self, client: AsyncClient, test_user: User
    ):
        """测试创建文章"""
        token = create_access_token(str(test_user.id))

        response = await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Test Post",
                "content": "This is the content of the test post.",
                "category": "Technology",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Post"
        assert data["status"] == "draft"  # 默认是草稿
        assert data["author"]["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_create_post_unauthorized(self, client: AsyncClient):
        """测试未登录创建文章"""
        response = await client.post(
            "/api/v1/posts",
            json={
                "title": "Test Post",
                "content": "This is the content.",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_posts(self, client: AsyncClient, test_user: User):
        """测试获取文章列表"""
        # 先创建一篇文章
        token = create_access_token(str(test_user.id))
        await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Published Post",
                "content": "This post will be published.",
            },
        )

        # 发布文章
        response = await client.post(
            "/api/v1/posts/1/publish",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        # 获取列表
        response = await client.get("/api/v1/posts")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "meta" in data

    @pytest.mark.asyncio
    async def test_get_post_detail(
        self, client: AsyncClient, test_user: User
    ):
        """测试获取文章详情"""
        token = create_access_token(str(test_user.id))

        # 创建文章
        create_response = await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Detail Test Post",
                "content": "Detailed content here.",
            },
        )
        post_id = create_response.json()["id"]

        # 获取详情
        response = await client.get(f"/api/v1/posts/{post_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Detail Test Post"
        assert data["content"] == "Detailed content here."

    @pytest.mark.asyncio
    async def test_update_own_post(
        self, client: AsyncClient, test_user: User
    ):
        """测试更新自己的文章"""
        token = create_access_token(str(test_user.id))

        # 创建文章
        create_response = await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Original Title",
                "content": "Original content.",
            },
        )
        post_id = create_response.json()["id"]

        # 更新文章
        response = await client.patch(
            f"/api/v1/posts/{post_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Updated Title",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["content"] == "Original content."  # 未更新的字段保持不变

    @pytest.mark.asyncio
    async def test_publish_post(
        self, client: AsyncClient, test_user: User
    ):
        """测试发布文章"""
        token = create_access_token(str(test_user.id))

        # 创建文章（草稿状态）
        create_response = await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "Draft Post",
                "content": "Will be published.",
            },
        )
        post_id = create_response.json()["id"]

        # 发布
        response = await client.post(
            f"/api/v1/posts/{post_id}/publish",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "published"
        assert data["published_at"] is not None

    @pytest.mark.asyncio
    async def test_delete_post(
        self, client: AsyncClient, test_user: User
    ):
        """测试删除文章"""
        token = create_access_token(str(test_user.id))

        # 创建文章
        create_response = await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "To Delete",
                "content": "Will be deleted.",
            },
        )
        post_id = create_response.json()["id"]

        # 删除
        response = await client.delete(
            f"/api/v1/posts/{post_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

        # 确认已删除（再次获取应返回 404）
        response = await client.get(f"/api/v1/posts/{post_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_my_posts(
        self, client: AsyncClient, test_user: User
    ):
        """测试获取我的文章（包括草稿）"""
        token = create_access_token(str(test_user.id))

        # 创建草稿
        await client.post(
            "/api/v1/posts",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": "My Draft",
                "content": "Draft content.",
            },
        )

        # 获取我的文章
        response = await client.get(
            "/api/v1/posts/my/posts",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1
