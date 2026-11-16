"""会话累计计费（2026-11-14 用户定：一个会话累加，不每轮归零）。

现场/根因：billed_* 由 reset_task_usage 每 turn 归零、turn 收尾只把本轮写进
会话 KV → 前端「已计费」每轮清零。修复：turn 开始从会话 KV 续读 billed_*
基数（同 used floor 模式），step 实时事件与 turn 收尾统一走 _billed_payload
（基数 + 本 turn usage），保证推送与落库同口径。

用例：
1. 预置 KV billed_in=100 → execute 一轮（假 task_id 走取消早退，零 LLM 调用）→
   monkeypatch get_task_usage 返回本轮 10/5/0.1 → 收尾回写必须 =110/55/0.6
   （修复前只写本轮 10/5/0.1，基数丢失 = "每轮重新计费"现场）。
2. _billed_payload 纯函数口径：基数 + 本轮。
"""

import asyncio

import pytest
from sqlalchemy import text

from app.agent.graphs.main_graph import AgentGraph
from app.agent.tools.session_context import get_session_context, set_session_context

SID = "test_session_billing_accum"


async def _ensure_test_session():
    """session_contexts.session_id 有 FK → 先建 sessions 行（幂等：先清后插）。

    用**独立引擎**建行：全量跑时全局池里可能有其它测试用独立 loop
    （如 sync 测试内 asyncio.run）留下的连接，跨 loop ping 会炸
    （RuntimeError: attached to a different loop，服务器全量实测）。
    本测试自建自毁引擎，既免疫污染，也不给后续测试留脏连接。
    """
    from app.db.session import create_async_db_engine

    eng = create_async_db_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text("DELETE FROM session_contexts WHERE session_id=:s"), {"s": SID})
            await conn.execute(
                text("DELETE FROM sessions WHERE session_id=:s"), {"s": SID})
            uid = (await conn.execute(
                text("SELECT id FROM users ORDER BY id LIMIT 1"))).first()
            assert uid, "库内需至少一个用户（sessions.user_id 外键）"
            await conn.execute(
                text("INSERT INTO sessions (session_id, user_id, title, status, is_deleted) "
                     "VALUES (:s, :u, 'billing-test', 'active', false)"),
                {"s": SID, "u": uid[0]})
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_billed_accumulates_across_turns(monkeypatch):
    # 全局池隔离：清掉前面测试（可能跑在独立 loop）留下的连接，
    # 本测试内 set_session_context/execute 的 KV 读写会在当前 loop 新建连接；
    # 结束后再 dispose 一次，不给后续测试留跨 loop 脏连接。
    # （服务器实测：dispose 对死 loop 连接 DISPOSE_OK，之后查询正常）
    from app.db.session import engine as _global_engine

    await _global_engine.dispose()
    await _ensure_test_session()
    await set_session_context(SID, "context_usage", {
        "used": 5000, "max": 128000, "ratio": 0.04,
        "compress_count": 1, "cc_ver": 3,
        "billed_in": 100, "billed_out": 50, "billed_cost": 0.5, "last_in": 30,
    })

    try:
        # 本轮 usage：模拟 LLM 已产生 10/5/0.1 的计费（不打真 LLM）
        from app.agent.llm import factory as _factory
        monkeypatch.setattr(_factory, "get_task_usage", lambda *a, **k: {
            "prompt_tokens": 10, "completion_tokens": 5, "cost": 0.1,
            "calls": 1, "peak_in": 1000,
        })

        graph = AgentGraph()
        # 假 task_id → TaskManager 状态非 running → 取消早退（不打任何 LLM）；
        # turn 开始的 KV 续读与收尾的用量回写照常执行。
        result = await graph.execute(
            task="计费累计回归", session_id=SID, task_id="__billing_accum__")
        assert result is not None

        # 收尾 set_session_context 是 create_task 火即忘，等它落库
        await asyncio.sleep(0.3)
        kv = await get_session_context(SID, "context_usage")
        assert isinstance(kv, dict), "收尾必须把 context_usage 写回会话 KV"
        # 关键断言：基数 100/50/0.5 + 本轮 10/5/0.1 = 110/55/0.6（修复前=10/5/0.1）
        assert int(kv.get("billed_in") or 0) == 110, f"billed_in={kv.get('billed_in')}（应=基数100+本轮10）"
        assert int(kv.get("billed_out") or 0) == 55, f"billed_out={kv.get('billed_out')}（应=基数50+本轮5）"
        assert float(kv.get("billed_cost") or 0.0) == pytest.approx(0.6)
        # used floor 续读不受影响
        assert int(kv.get("used") or 0) >= 5000
    finally:
        await _global_engine.dispose()


def test_billed_payload_merges_base_and_turn():
    """_billed_payload 口径 = 会话 KV 基数 + 本 turn usage（step 与收尾共用）。"""
    g = AgentGraph.__new__(AgentGraph)  # 跳过 __init__（无需建组件）
    g._billed_base_in, g._billed_base_out, g._billed_base_cost = 100, 50, 0.5
    p = g._billed_payload(
        {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.1})
    assert p == {"billed_in": 110, "billed_out": 55, "billed_cost": 0.6}
    # 无基数（新会话）= 本轮原值
    g._billed_base_in, g._billed_base_out, g._billed_base_cost = 0, 0, 0.0
    p = g._billed_payload(
        {"prompt_tokens": 7, "completion_tokens": 3, "cost": 0.2})
    assert p == {"billed_in": 7, "billed_out": 3, "billed_cost": 0.2}
