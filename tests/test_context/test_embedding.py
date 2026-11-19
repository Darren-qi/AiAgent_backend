"""p2 必测：zhipu embedding 移植 + API usage 校准钩子（方案 §9.2）。

全部离线：embedding 走 httpx.MockTransport，manager 注入假 embed_fn。
运行：.venv/bin/python -m pytest tests/test_context/ -v
"""
from __future__ import annotations

import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.agent.context import (  # noqa: E402
    ContextConfig,
    ContextItem,
    ContextManager,
    EmbeddingError,
    ItemType,
    LoadState,
    RecallConfig,
    ZhipuEmbedder,
    calibrate,
    calibration_ratio,
    count_tokens,
    reset_calibration,
)

DIM = 2048


def _vec(fill: float = 0.5) -> list:
    return [fill] * DIM


def _reverse_handler(calls: list):
    """200 响应：data 故意倒序（验证按 index 还原顺序）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        data = [{"index": i, "embedding": _vec(0.1 * i)}
                for i in range(len(payload["input"]))]
        return httpx.Response(200, json={"data": list(reversed(data))})
    return handler


# ── embedding 客户端 ──

def test_embed_sorts_by_index():
    calls = []
    der = ZhipuEmbedder(api_key="k", transport=httpx.MockTransport(_reverse_handler(calls)))
    vecs = der.embed(["a", "b", "c"])
    assert len(vecs) == 3
    assert vecs[0][0] == pytest.approx(0.0)
    assert vecs[1][0] == pytest.approx(0.1)
    assert vecs[2][0] == pytest.approx(0.2)
    assert calls[0].url.path == "/api/paas/v4/embeddings"
    assert json.loads(calls[0].content)["model"] == "embedding-3"


def test_embed_splits_batches_by_64():
    calls = []
    der = ZhipuEmbedder(api_key="k", transport=httpx.MockTransport(_reverse_handler(calls)))
    vecs = der.embed([f"t{i}" for i in range(70)])
    assert [len(json.loads(r.content)["input"]) for r in calls] == [64, 6]
    assert len(vecs) == 70


def test_embed_retries_on_429():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        payload = json.loads(request.content)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": _vec()}
            for i in range(len(payload["input"]))]})

    der = ZhipuEmbedder(api_key="k", max_retries=2, backoff=0,
                        transport=httpx.MockTransport(handler))
    vecs = der.embed(["hello"])
    assert state["n"] == 2
    assert len(vecs) == 1 and len(vecs[0]) == DIM


def test_missing_key_graceful():
    der = ZhipuEmbedder(api_key="")
    with pytest.raises(EmbeddingError):
        der.embed(["x"])
    assert der.embed_one("x") is None   # 插拔位：失败→None→向量层跳过


def test_embed_one_failure_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    der = ZhipuEmbedder(api_key="k", max_retries=0, backoff=0,
                        transport=httpx.MockTransport(handler))
    assert der.embed_one("x") is None


def test_embed_dimension_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(200, json={"data": [
            {"index": i, "embedding": [0.1] * 100}
            for i in range(len(payload["input"]))]})

    der = ZhipuEmbedder(api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError):
        der.embed(["x"])
    assert der.embed_one("x") is None


# ── manager 卸载时补算 embedding（方案 §0.2）──

def test_manager_embeds_unloaded_items():
    seen = []

    def embed(text: str):
        seen.append(text)
        return [1.0, 0.0]

    # 显式给 compress_trigger_ratio：本测的是"卸载后补算 embedding"，需要压缩真的发生。
    # 2026-11-12 默认 trigger 改 1.0（超 128K 才压）后，未超限 turn_end 不再压缩，
    # 故此处降 trigger 让预算压缩路径走到（与默认策略解耦）。
    mgr = ContextManager(ContextConfig(max_tokens=3000, compress_trigger_ratio=0.7),
                         embed_fn=embed)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):
        mgr.on_observation(f"o{i}", "x" * 6000, step=i, tool="t",
                           params_summary="p", one_line=f"L{i}")
    mgr.on_turn_end(step_count=5)
    offloaded = [it for it in mgr.items.values()
                 if it.state == LoadState.INDEX_ONLY and it.external_ref]
    assert offloaded, "应有卸载到索引态的项"
    for it in offloaded:
        assert mgr.recall_engine.has_embedding(it.id), f"{it.id} 应已补算向量"
        ref = it.external_ref
        assert ref is not None
        got = mgr.load_by_ref(ref)
        assert got is not None and got.startswith("x")   # 原文可恢复
    assert any(s.startswith("x") for s in seen), "应 embed 过原文"


def test_knowledge_embedded_at_step_start():
    seen = []
    mgr = ContextManager(ContextConfig(),
                         embed_fn=lambda t: seen.append(t) or [1.0, 0.0])
    mgr.on_session_start("SYS", "", "REQ")
    mgr.register(ContextItem(id="k1", type=ItemType.KNOWLEDGE,
                             content="knowledge body", recoverable=True))
    assert not mgr.recall_engine.has_embedding("k1")   # 注册时还不算
    mgr.on_step_start(step=1, query="", build_only=True)
    assert mgr.recall_engine.has_embedding("k1")       # 召回前补算
    assert "knowledge body" in seen


def test_embed_failure_does_not_block():
    def boom(text: str):
        raise RuntimeError("network down")

    mgr = ContextManager(ContextConfig(max_tokens=3000), embed_fn=boom)
    mgr.on_session_start("SYS", "", "REQ")
    mgr.register(ContextItem(id="k1", type=ItemType.KNOWLEDGE,
                             content="kb", recoverable=True))
    build = mgr.on_step_start(step=1, query="", build_only=True)   # 不应抛
    assert build.prompt
    assert not mgr.recall_engine.has_embedding("k1")


def test_no_embedding_when_vector_layer_off():
    calls = []
    cfg = ContextConfig(recall=RecallConfig(mode="trigger_only"))
    mgr = ContextManager(cfg, embed_fn=lambda t: calls.append(t) or [1.0, 0.0])
    mgr.on_session_start("SYS", "", "REQ")
    mgr.register(ContextItem(id="k1", type=ItemType.KNOWLEDGE,
                             content="kb", recoverable=True))
    mgr.on_step_start(step=1, query="", build_only=True)
    assert calls == []                    # 向量层未启用 → 不烧 embedding 调用
    assert not mgr.recall_engine.has_embedding("k1")


# ── API usage 校准钩子（方案 §2：事前 tiktoken、事后 API usage 校准）──

def test_api_usage_calibration_hook():
    text = "hello world"
    base = count_tokens(text)
    assert base > 0
    reset_calibration()
    try:
        assert calibration_ratio() == 1.0
        assert count_tokens(text) == base          # 未校准 = 原始 tiktoken 值
        r = calibrate(base * 2, base)              # 真实 usage 是估算的 2 倍
        assert abs(r - 2.0) < 1e-9
        assert count_tokens(text) == base * 2      # 后续估算按比例修正
        assert calibrate(0, base) == 2.0           # 非法样本忽略
        assert calibrate(base, 0) == 2.0
        assert count_tokens("") == 0               # 空串恒 0
    finally:
        reset_calibration()
    assert calibration_ratio() == 1.0
    assert count_tokens(text) == base
