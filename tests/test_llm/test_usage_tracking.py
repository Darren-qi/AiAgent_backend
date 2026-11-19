"""P1/P2（2026-11-14）：真实 usage 追踪 —— calibrate 接线 + per-turn 计费累计。

覆盖：
1. count_tokens(calibrated=False) 不受校准比例影响（供 calibrate 输入，防自激）
2. factory.chat 每次调用后：calibrate 被真实 prompt_tokens 驱动（生产零调用点 → 已接线）
3. set_usage_scope/reset_task_usage/get_task_usage 按 scope 累计 input/output/cost/calls/peak_in
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.context.budget import (
    calibrate,
    calibration_ratio,
    count_tokens,
    reset_calibration,
)
from app.agent.llm import factory as factory_mod
from app.agent.llm.factory import (
    LLMFactory,
    get_last_usage,
    get_task_usage,
    reset_task_usage,
    set_usage_scope,
)
from app.agent.llm.types import LLMResponse, ModelConfig, ModelProvider


@pytest.fixture(autouse=True)
def _clean_state():
    reset_calibration()
    factory_mod._TASK_USAGE.clear()
    factory_mod._LAST_USAGE.update(
        {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
    yield
    reset_calibration()
    factory_mod._TASK_USAGE.clear()
    factory_mod._LAST_USAGE.update(
        {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})


class TestCountTokensCalibratedFlag:
    def test_uncalibrated_ignores_ratio(self):
        """calibrated=False 返回原始估算，不受 _calibration_ratio 影响。"""
        calibrate(2000, 1000)  # ratio -> 2.0
        assert calibration_ratio() == pytest.approx(2.0)
        text = "hello world " * 50
        raw = count_tokens(text, calibrated=False)
        scaled = count_tokens(text)
        assert scaled == pytest.approx(raw * 2, rel=0.05)
        # 再次校准不会自激：用原始估算做分母，比例收敛到真实比值
        calibrate(raw * 3, raw)
        assert calibration_ratio() == pytest.approx(3.0)


class TestFactoryUsageTracking:
    def _mock_factory(self) -> LLMFactory:
        factory = LLMFactory.get_instance()
        cfg = ModelConfig(
            name="test-model",
            provider=ModelProvider.DEEPSEEK,
            display_name="Test",
            # 成本压到极小，确保 budget check 不会拦截
            input_cost_per_1k=0.000001,
            output_cost_per_1k=0.000002,
        )
        factory.router.select_model = (
            lambda strategy=None, required_capabilities=None: cfg)
        resp = LLMResponse(
            content="ok",
            model="test-model",
            provider=ModelProvider.DEEPSEEK,
            usage={"prompt_tokens": 1234, "completion_tokens": 56,
                   "total_tokens": 1290},
            cost=0.01,
            latency_ms=1.0,
        )
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(return_value=resp)
        factory._provider_instances[ModelProvider.DEEPSEEK] = mock_provider
        return factory

    @pytest.mark.asyncio
    async def test_chat_accumulates_and_calibrates(self):
        """一次 chat：累计到 scope + 更新 last + calibrate 被真实值驱动。"""
        factory = self._mock_factory()
        set_usage_scope("task-x")
        reset_task_usage("task-x")

        out = await factory.chat([{"role": "user", "content": "你好世界"}])
        assert out.content == "ok"

        tu = get_task_usage("task-x")
        assert tu["prompt_tokens"] == 1234
        assert tu["completion_tokens"] == 56
        assert tu["peak_in"] == 1234
        assert tu["calls"] == 1
        assert tu["cost"] == pytest.approx(0.01)

        assert get_last_usage()["prompt_tokens"] == 1234
        # calibrate 接线验证：真实 1234 vs 估算（肯定 != 1234）→ 比例被更新
        assert calibration_ratio() != 1.0

    @pytest.mark.asyncio
    async def test_reset_scopes_isolated(self):
        """reset 清零本 scope，不影响其他 scope；重复调用累加。"""
        factory = self._mock_factory()
        set_usage_scope("a")
        reset_task_usage("a")
        reset_task_usage("b")

        await factory.chat([{"role": "user", "content": "第一条"}])
        await factory.chat([{"role": "user", "content": "第二条"}])

        assert get_task_usage("a")["calls"] == 2
        assert get_task_usage("a")["prompt_tokens"] == 2468
        assert get_task_usage("b")["prompt_tokens"] == 0

        reset_task_usage("a")
        assert get_task_usage("a")["prompt_tokens"] == 0
        assert get_task_usage("a")["calls"] == 0
