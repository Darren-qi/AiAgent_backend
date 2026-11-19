"""用户级 DeepSeek API Key（2026-11-14 用户定：设置页填自己的 key，
持久存储，后续使用该系统都消耗用户自己的 key）。

链路：设置页 PUT /users/profile/llm-key → users.deepseek_api_key →
turn 开始 apply_turn_user_api_key(session_id) → contextvar →
factory.chat 注入 ChatRequest.api_key → DeepSeekProvider._pick_client
走用户专属 client 计费；未填/查不到一律回落系统 key。

用例：
1. mask_key 纯函数（GET 状态接口只回掩码不回全文）。
2. contextvar set/get/clear。
3. ChatRequest.api_key 透传 + DeepSeekProvider._pick_client
   （有 key→用户 client 且按 key 复用、无→系统 client）。
4. load/apply：建 sessions+users 行（带自己的 key）→ 装载进 contextvar；
   无 session → 清空回落系统 key。
5. router 回落：系统无 DEEPSEEK_API_KEY 但用户有 key → 仍列出 DeepSeek
   模型；清掉用户 key → 不再列出。
6. validate_deepseek_key：401→无效；200→通过；网络异常→拒绝保存。
7. 接线源码断言：main_graph.execute 调 apply hook、factory.chat 注入
   request.api_key（动态全链路会污染 LLMFactory 单例，故静态断言 +
   各环节独立动态测）。

注：HTTP 层（GET/PUT /profile/llm-key）无 client fixture 基建
（test_api 历史缺失、启用会写真实库，见 tests/test_api/conftest.py），
部署后用真实请求 e2e 验证；本文件覆盖其全部核心逻辑。
"""

import inspect

import pytest
from sqlalchemy import text

from app.agent.llm.user_api_key import (
    apply_turn_user_api_key,
    get_user_api_key,
    load_user_deepseek_key,
    mask_key,
    set_user_api_key,
    validate_deepseek_key,
)

SID = "test_user_api_key_sid"
UNAME = "ukey_test_user"


# ── 1. 掩码 ──────────────────────────────────────────────────────────

def test_mask_key():
    assert mask_key(None) == ""
    assert mask_key("") == ""
    assert mask_key("short") == "***"
    assert mask_key("sk-abcdef123456") == "sk-***3456"
    # 接口绝不能回全文
    k = "sk-verysecretkey0001"
    assert k not in mask_key(k)


# ── 2. contextvar ───────────────────────────────────────────────────

def test_contextvar_set_get_clear():
    set_user_api_key("  sk-abc  ")
    assert get_user_api_key() == "sk-abc"  # 自动 trim
    set_user_api_key("")
    assert get_user_api_key() == ""  # 空串 = 回落系统 key
    set_user_api_key(None)
    assert get_user_api_key() == ""


# ── 3. ChatRequest 透传 + provider 选 client ────────────────────────

def test_chatrequest_api_key_and_pick_client():
    from app.agent.llm.providers.deepseek import DeepSeekProvider
    from app.agent.llm.types import ChatMessage, ChatRequest, ModelConfig, ModelProvider

    cfg = ModelConfig(name="deepseek-chat", display_name="DeepSeek Chat",
                      provider=ModelProvider.DEEPSEEK)
    p = DeepSeekProvider(cfg)
    req = ChatRequest(messages=[ChatMessage(role="user", content="hi")])

    # 默认不注入 → 系统 client
    assert req.api_key is None
    assert p._pick_client(req) is p.client

    # 用户 key → 用户专属 client，且按 key 复用（不每请求重建）
    req.api_key = "sk-user-1"
    c1 = p._pick_client(req)
    assert c1 is not p.client
    assert p._pick_client(req) is c1
    assert p._keyed_clients["sk-user-1"] is c1

    # 换 key → 另一个 client
    req.api_key = "sk-user-2"
    assert p._pick_client(req) is not c1

    # 清空 → 回到系统 client
    req.api_key = None
    assert p._pick_client(req) is p.client


# ── 4. session → user → key 装载 ────────────────────────────────────

async def _seed_user_with_key(key: str) -> None:
    """独立引擎建 users+sessions 行（幂等：先清后插），免疫全局池跨 loop 污染。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import create_async_db_engine
    from app.models.experience import SessionModel
    from app.models.user import User

    eng = create_async_db_engine()
    try:
        S = async_sessionmaker(eng, expire_on_commit=False)
        async with S() as db:
            await db.execute(
                text("DELETE FROM sessions WHERE session_id=:s"), {"s": SID})
            await db.execute(
                text("DELETE FROM users WHERE username=:u"), {"u": UNAME})
            user = User(username=UNAME, email=f"{UNAME}@t.dev",
                        hashed_password="x", deepseek_api_key=key or None)
            db.add(user)
            await db.flush()
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            db.add(SessionModel(
                session_id=SID, user_id=user.id, title="ukey-test",
                status="active", is_deleted=False,
                created_at=now, updated_at=now))
            await db.commit()
    finally:
        await eng.dispose()


async def _cleanup() -> None:
    from app.db.session import create_async_db_engine
    eng = create_async_db_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text("DELETE FROM sessions WHERE session_id=:s"), {"s": SID})
            await conn.execute(
                text("DELETE FROM users WHERE username=:u"), {"u": UNAME})
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_load_and_apply_turn_key():
    from app.db.session import engine as _global_engine

    await _global_engine.dispose()  # 清前面测试可能留下的跨 loop 连接
    try:
        await _seed_user_with_key("sk-user-db-key")

        # 命中：session → user → key
        assert await load_user_deepseek_key(SID) == "sk-user-db-key"
        await apply_turn_user_api_key(SID)
        assert get_user_api_key() == "sk-user-db-key"

        # 无 session → 清空（回落系统 key）
        await apply_turn_user_api_key(None)
        assert get_user_api_key() == ""

        # 不存在的 session → 空串，不炸
        assert await load_user_deepseek_key("no_such_session_xxx") == ""

        # 无 key 的用户 → 空串
        await _cleanup()
        await _seed_user_with_key("")
        assert await load_user_deepseek_key(SID) == ""
    finally:
        await _cleanup()
        await _global_engine.dispose()
        set_user_api_key("")


# ── 5. router：系统无 key 时用户 key 兜底选型 ───────────────────────

def test_router_falls_back_to_user_key(monkeypatch):
    from app.agent.llm.router import ModelRouter
    from app.agent.llm.types import ModelProvider

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    try:
        # 系统没配 key + 用户没填 → DeepSeek 不可选
        set_user_api_key("")
        models = ModelRouter({}).get_available_models()
        assert not any(m.provider is ModelProvider.DEEPSEEK for m in models)

        # 用户填了自己的 key → DeepSeek 仍可选（router 的 key 存在性检查过）
        set_user_api_key("sk-user-fallback")
        models = ModelRouter({}).get_available_models()
        assert any(m.provider is ModelProvider.DEEPSEEK for m in models)
    finally:
        set_user_api_key("")


# ── 6. 保存前验证（mock DeepSeek /models，不打真实网络） ─────────────

@pytest.mark.asyncio
async def test_validate_deepseek_key(monkeypatch):
    import httpx

    class _Resp:
        def __init__(self, code):
            self.status_code = code

    def _fake_client_cls(status=None, exc=None):
        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                if exc:
                    raise exc
                return _Resp(status)

        return _FakeClient

    # 401 → Key 无效，拒绝保存
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client_cls(status=401))
    ok, msg = await validate_deepseek_key("sk-bad")
    assert ok is False and msg == "Key 无效"

    # 200 → 通过
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client_cls(status=200))
    ok, msg = await validate_deepseek_key("sk-good")
    assert ok is True and msg == ""

    # 网络异常 → 也拒绝（避免存入坏 key）
    monkeypatch.setattr(httpx, "AsyncClient",
                        _fake_client_cls(exc=RuntimeError("boom")))
    ok, msg = await validate_deepseek_key("sk-whatever")
    assert ok is False and "网络异常" in msg

    # 空 key → 拒绝
    ok, msg = await validate_deepseek_key("   ")
    assert ok is False


# ── 7. 接线断言（main_graph hook + factory 注入点） ──────────────────

def test_wiring_call_sites():
    from app.agent.graphs.main_graph import AgentGraph
    from app.agent.llm.factory import LLMFactory

    exec_src = inspect.getsource(AgentGraph.execute)
    assert "apply_turn_user_api_key" in exec_src, \
        "execute() turn 开始必须装载用户 key"

    chat_src = inspect.getsource(LLMFactory.chat)
    assert "request.api_key" in chat_src and "get_user_api_key" in chat_src, \
        "factory.chat DeepSeek 选型时必须注入用户 key"
