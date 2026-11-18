"""会话列表删除 → 级联清理（子表 + 磁盘任务目录）端点测试。

前端会话列表的删除按钮走 `DELETE /api/v1/agent/execute/?task_id=<session_id>`
（src/api/agent.js `session.delete`），断言它确实调用了 cleanup_session。
不连真实 DB：把 AsyncSessionLocal 与 cleanup_session 都换成替身。
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class TestDeleteSessionCascade:
    @pytest.mark.asyncio
    async def test_delete_calls_cleanup(self):
        from app.main import app

        called = {}

        async def fake_cleanup(db, session_id, *, delete_parent=False):
            called["session_id"] = session_id
            called["delete_parent"] = delete_parent
            return {"dirs": ["/www/tasks/auto_project_1"],
                    "tables": {"session_files": 3}, "parent": True}

        with patch("app.api.v1.endpoints.agent.AsyncSessionLocal",
                   lambda: _DummySession()), \
             patch("app.agent.session_cleanup.cleanup_session",
                   side_effect=fake_cleanup):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://test") as client:
                resp = await client.delete(
                    "/api/v1/agent/execute/", params={"task_id": "session_zzz"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert called.get("session_id") == "session_zzz"
        assert called.get("delete_parent") is True, "sessions 行也要删"

    @pytest.mark.asyncio
    async def test_cleanup_failure_still_returns_success(self):
        """级联清理失败不得让删除接口 500（会话本身已尽力删除）。"""
        from app.main import app

        async def boom(*a, **k):
            raise RuntimeError("模拟清理炸了")

        with patch("app.api.v1.endpoints.agent.AsyncSessionLocal",
                   lambda: _DummySession()), \
             patch("app.agent.session_cleanup.cleanup_session",
                   side_effect=boom):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://test") as client:
                resp = await client.delete(
                    "/api/v1/agent/execute/", params={"task_id": "session_zzz"})

        assert resp.status_code == 200
        assert resp.json()["success"] is True
