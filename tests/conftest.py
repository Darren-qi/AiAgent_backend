"""Test fixtures and configuration."""

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _calibration_isolation():
    """每个测试前后重置 token 校准比例（P1 2026-11-14）。

    factory._do_chat 现在会用真实/ mock 的 prompt_tokens 调 calibrate()，
    全局 _calibration_ratio 会被测试里的 mock usage 改脏，
    泄漏到其他测试（test_context 预算断言因此漂移）。
    """
    from app.agent.context.budget import reset_calibration
    reset_calibration()
    yield
    reset_calibration()


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
    settings.app_name = "RiffCode Test"
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
