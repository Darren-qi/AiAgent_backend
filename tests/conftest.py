"""Test fixtures and configuration."""

import pytest
import asyncio
from typing import Generator, AsyncGenerator
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_settings():
    """Mock settings fixture"""
    settings = MagicMock()
    settings.app_name = "AiAgent Test"
    settings.debug = True
    settings.database_url = "postgresql+asyncpg://test:test@localhost:5432/test_db"
    settings.redis_url = "redis://localhost:6379/0"
    settings.secret_key = "test-secret-key"
    return settings


@pytest.fixture
def mock_user():
    """Mock user fixture"""
    return {
        "user_id": "test-user-123",
        "username": "testuser",
        "email": "test@example.com",
        "role": "user",
    }


@pytest.fixture
def mock_agent_context():
    """Mock agent context fixture"""
    return {
        "session_id": "test-session-123",
        "user_id": "test-user-123",
        "request_id": "test-request-456",
        "timestamp": "2026-03-21T10:00:00Z",
    }


@pytest.fixture
def mock_skill_result():
    """Mock skill result fixture"""
    return {
        "success": True,
        "result": {"message": "Skill executed successfully"},
        "skill_name": "test_skill",
        "execution_time": 0.5,
    }


@pytest.fixture
def mock_storage_result():
    """Mock storage result fixture"""
    return {
        "success": True,
        "url": "https://storage.example.com/test-file.jpg",
        "file_id": "file-123",
        "size": 1024,
    }
