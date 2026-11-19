"""LLM 层打点断言（阶段六 Trace，2026-11-17）。

计划 §阶段六-3：llm/factory 每次调用 log model/latency_ms/usage
（此前 llm 包 0 条日志——8 个 provider 算好 latency_ms 即丢）。
验收走三处交叉定位的"日志（app.log 含 model/latency）"一角。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent import trace as trace_mod
from app.agent.llm.factory import LLMFactory
from app.agent.llm.types import LLMResponse, ModelConfig, ModelProvider


@pytest.fixture(autouse=True)
def _clean():
    trace_mod._state["path"] = None
    trace_mod._state["session_id"] = None
    yield
    trace_mod._state["path"] = None
    trace_mod._state["session_id"] = None


def _mock_factory() -> LLMFactory:
    factory = LLMFactory.get_instance()
    cfg = ModelConfig(
        name="trace-model",
        provider=ModelProvider.DEEPSEEK,
        display_name="Trace",
        input_cost_per_1k=0.000001,
        output_cost_per_1k=0.000002,
    )
    factory.router.select_model = (
        lambda strategy=None, required_capabilities=None: cfg)
    resp = LLMResponse(
        content="ok",
        model="trace-model",
        provider=ModelProvider.DEEPSEEK,
        usage={"prompt_tokens": 111, "completion_tokens": 22,
               "total_tokens": 133},
        cost=0.001,
        latency_ms=1.0,
    )
    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(return_value=resp)
    factory._provider_instances[ModelProvider.DEEPSEEK] = mock_provider
    return factory


async def test_chat_emits_llm_call_run_log(tmp_path, monkeypatch):
    """factory.chat → JSONL llm_call 事件带 model/latency/usage。"""
    monkeypatch.setitem(trace_mod._state, "path", tmp_path / "run.jsonl")
    factory = _mock_factory()
    await factory.chat([{"role": "user", "content": "打点测试"}])

    path = trace_mod.get_run_log_path()
    recs = [json.loads(l) for l in path.read_text().splitlines()]
    llm_calls = [e for e in recs if e["event"] == "llm_call"]
    assert llm_calls, f"缺 llm_call 事件: {recs}"
    ev = llm_calls[-1]
    assert ev["model"] == "trace-model"
    assert isinstance(ev["latency_ms"], (int, float)) and ev["latency_ms"] >= 0
    assert ev["prompt_tokens"] == 111 and ev["completion_tokens"] == 22
    assert "request_id" in ev


async def test_chat_logs_model_latency_to_logger():
    """factory.chat → loguru 日志行含 model/latency（app.log 可检索）。"""
    from loguru import logger as loguru_logger

    captured = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        factory = _mock_factory()
        await factory.chat([{"role": "user", "content": "日志行测试"}])
    finally:
        loguru_logger.remove(sink_id)

    lines = [str(m) for m in captured]
    hit = [ln for ln in lines if "[LLM]" in ln and "trace-model" in ln]
    assert hit, f"未捕获 [LLM] 打点行: {lines[-5:]}"
    assert "latency_ms=" in hit[0]
    assert "prompt_tokens=111" in hit[0]
