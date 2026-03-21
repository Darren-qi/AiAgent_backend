"""LLM 模块测试"""

import pytest
from unittest.mock import MagicMock, patch
from app.agent.llm.types import ModelConfig, ModelProvider, ChatMessage, ChatRequest
from app.agent.llm.router import ModelRouter
from app.agent.llm.budget_manager import BudgetManager, BudgetStatus


class TestModelConfig:
    """模型配置测试"""

    def test_create_config(self):
        """测试创建配置"""
        config = ModelConfig(
            name="test-model",
            provider=ModelProvider.DEEPSEEK,
            display_name="Test Model",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
        )
        assert config.name == "test-model"
        assert config.provider == ModelProvider.DEEPSEEK
        assert config.input_cost_per_1k == 0.001


class TestChatRequest:
    """聊天请求测试"""

    def test_create_request(self):
        """测试创建请求"""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]
        request = ChatRequest(
            messages=messages,
            model="test-model",
            temperature=0.7,
        )
        assert len(request.messages) == 2
        assert request.temperature == 0.7
        assert request.model == "test-model"


class TestBudgetManager:
    """预算管理器测试"""

    @pytest.mark.asyncio
    async def test_check_budget_normal(self):
        """测试正常预算检查"""
        manager = BudgetManager()
        allowed, status = await manager.check_budget(0.1)
        assert allowed is True
        assert status == BudgetStatus.NORMAL

    @pytest.mark.asyncio
    async def test_record_usage(self):
        """测试记录使用量"""
        manager = BudgetManager()
        initial_used = manager.get_status().daily_used
        await manager.record_usage(1.0)
        new_used = manager.get_status().daily_used
        assert new_used == initial_used + 1.0

    def test_get_status(self):
        """测试获取状态"""
        manager = BudgetManager()
        status = manager.get_status()
        assert status.daily_limit > 0
        assert status.monthly_limit > 0


class TestModelRouter:
    """模型路由器测试"""

    def test_create_router(self):
        """测试创建路由器"""
        router = ModelRouter({})
        assert router.default_strategy == "balance"

    def test_get_available_models(self):
        """测试获取可用模型"""
        router = ModelRouter({})
        models = router.get_available_models()
        assert isinstance(models, list)

    def test_strategies_available(self):
        """测试策略可用性"""
        router = ModelRouter({})
        assert "cost" in router.strategies
        assert "quality" in router.strategies
        assert "balance" in router.strategies
