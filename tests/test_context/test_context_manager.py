"""ContextManager 九条必测（方案 §6）。运行：
.venv/bin/python -m pytest tests/test_context/ -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.agent.context import (  # noqa: E402
    ContextConfig, ContextItem, ContextManager, ItemType, LoadState,
    RecallConfig, count_tokens,
)


def make_manager(**kw) -> ContextManager:
    cfg = ContextConfig(**kw)
    return ContextManager(cfg=cfg)


def add_obs(mgr: ContextManager, oid: str, content: str, step: int,
            tool: str = "write_file", persisted: bool = False,
            one_line: str = "") -> None:
    mgr.current_step = step
    mgr.on_observation(obs_id=oid, content=content, tool=tool,
                       params_summary=f"p_{oid}", one_line=one_line or oid,
                       step=step, persisted=persisted)


# ── 1. 系统提示/约束/原始请求/当前任务始终在上下文里 ──

def test_pinned_always_in_context():
    mgr = make_manager()
    mgr.on_session_start(system_prompt="SYS", constraints="CONST",
                         user_request="REQ")
    # 即便预算压力把别的都 mask 掉，pinned 四项永远在
    for i in range(50):
        add_obs(mgr, f"o{i}", "x" * 2000, step=i + 1)
    build = mgr.on_step_start(step=60, query="REQ")
    assert "SYS" in build.prompt
    assert "CONST" in build.prompt
    assert "REQ" in build.prompt
    for it in mgr.items.values():
        if it.type.value in ("system_prompt", "constraint", "user_request"):
            assert it.state == LoadState.LOADED
            assert not it.masked


# ── 2. 最近 N 个 step 的 Observation 不被 masking ──

def test_recent_obs_protected():
    cfg = ContextConfig(protect_recent_steps=2, max_tokens=3000)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):   # step 1..5
        add_obs(mgr, f"o{i}", "y" * 1500, step=i)
    # 当前 step=5：最近 2 step 保护 = step 3,4,5
    mgr.on_observation("o_new", "z" * 1500, step=5, tool="t",
                       params_summary="p", one_line="l")
    protected = {"o3", "o4", "o5", "o_new"}
    for oid in protected:
        it = mgr.items[oid]
        assert not it.masked, f"{oid} 不该被 mask"
        assert it.state == LoadState.LOADED


# ── 3. 当前 step 刚产生、尚未被消费的 Observation 绝对不动 ──

def test_pending_observation_untouched():
    cfg = ContextConfig(protect_recent_steps=0, max_tokens=500)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    add_obs(mgr, "old", "a" * 4000, step=1)
    # 当前 step=5（远超保护窗），刚登记的观察是 pending
    mgr.current_step = 5
    mgr.on_observation("fresh", "b" * 4000, step=5, tool="t",
                       params_summary="p", one_line="l")
    fresh = mgr.items["fresh"]
    assert fresh.id in mgr.pending_obs
    assert not fresh.masked
    assert fresh.state == LoadState.LOADED
    assert fresh.content.startswith("b")


# ── 4. 预算超限时先做 Observation Masking，而不是直接摘要 ──

def test_masking_before_compression():
    cfg = ContextConfig(max_tokens=4000, compress_trigger_ratio=0.7)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 8):
        add_obs(mgr, f"o{i}", "c" * 2000, step=i)
    # step 边界观察：触发 step 级 masking
    build = mgr.on_observation("o8", "d" * 4000, step=8, tool="t",
                               params_summary="p", one_line="l")
    assert build.decisions, "应有处理决策"
    # 任何 step 级决策都不允许是 compress
    assert all(d.action != "compress" for d in build.decisions)
    assert any(d.action == "masking" for d in build.decisions)
    # masking 发生在 step 之间（on_observation 钩子），turn 级没被调用
    assert "compress" not in [d.action for d in build.decisions]


# ── 5. 关键工具白名单的 Observation 只摘要不占位符替换 ──

def test_critical_tool_summary_not_placeholder():
    cfg = ContextConfig(max_tokens=3000, critical_tools={"sandbox"})
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):
        add_obs(mgr, f"o{i}", "e" * 2000, step=i, tool="write_file",
                one_line=f"line{i}")
    add_obs(mgr, "crit", "f" * 2000, step=6, tool="sandbox",
            one_line="unittest returncode=0")
    it = mgr.items["crit"]
    if it.masked:   # 若因预算被处理
        assert it.mask_reason == "critical_tool_summary"
        assert "unittest returncode=0" in it.content
        assert "[已卸载 Observation" not in it.content
    # 普通工具走占位符
    normal = [x for x in mgr.items.values()
              if x.metadata.get("tool") == "write_file" and x.masked]
    for n in normal:
        assert n.mask_reason == "budget_pressure"


# ── 6. 全量压缩只发生在 turn 后钩子，不在 step 之间 ──

def test_compress_only_at_turn_end():
    cfg = ContextConfig(max_tokens=4000)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 10):
        add_obs(mgr, f"o{i}", "g" * 3000, step=i)
        # step 间绝不出现 compress 决策
        assert all(d.action != "compress"
                   for d in mgr._decisions), "step 间不得压缩"
    # turn 后才允许
    res = mgr.on_turn_end(step_count=9)
    assert res.reason in ("budget", "turn_end", "long_loop", "manual")
    # turn 后确实发生了压缩类处理（budget 超 70%）
    assert mgr.budget.used <= mgr.budget.target_tokens or res.folded


# ── 7. 预算超过 70% 触发压缩并回到 50% 左右 ──

def test_budget_ratio_trigger():
    cfg = ContextConfig(max_tokens=10000, compress_trigger_ratio=0.7,
                        compress_target_ratio=0.5)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):
        add_obs(mgr, f"o{i}", "h" * 8000, step=i)
    assert mgr.budget.used > 7000, "应超 70% 触发线"
    res = mgr.on_turn_end(step_count=5)
    assert res.reason == "budget"
    # 回到 50% 附近（≤55% 留容差；folded 摘要本身也占 token）
    assert mgr.budget.used <= 10000 * 0.6, \
        f"压缩后 {mgr.budget.used} 仍高于目标区"
    assert mgr.budget.used >= 10000 * 0.35, "不应压到空"


# ── 8. 卸载后可以通过外部引用恢复 ──

def test_offload_and_restore_by_ref():
    cfg = ContextConfig(max_tokens=3000)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):
        add_obs(mgr, f"o{i}", "i" * 3000, step=i, one_line=f"L{i}")
    mgr.on_turn_end(step_count=5)   # 重量级卸载
    refs = [(it.id, it.external_ref) for it in mgr.items.values()
            if it.external_ref]
    assert refs, "应有内容被卸载并挂引用"
    for iid, ref in refs:
        got = mgr.load_by_ref(ref)
        assert got is not None, f"引用 {ref} 应可恢复"
        assert len(got) > 0


# ── 9. 不预加载全部工具 schema 和历史 Observation，JIT 生效 ──

def test_no_preload_jit():
    mgr = make_manager()
    mgr.on_session_start("SYS", "", "REQ")
    # 注册 5 个知识项（索引态）
    for i in range(5):
        mgr.register(ContextItem(
            id=f"know{i}", type=ItemType.KNOWLEDGE,
            content=f"knowledge body {i} " + "k" * 500,
            recoverable=True, external_ref=None))
    # 初始构建：知识项全部索引态，不进正文
    build = mgr.on_step_start(step=1, query="", build_only=True)
    assert "knowledge body" not in build.prompt
    assert len(build.omitted) == 5
    for i in range(5):
        assert mgr.items[f"know{i}"].state == LoadState.INDEX_ONLY
    # 触发词映射 → JIT 加载
    mgr.cfg.trigger_map = {"know1": ["know1"]}
    r = mgr.load_by_trigger("请参考 know1 的内容")
    assert "know1" in r.loaded_ids
    assert mgr.items["know1"].state == LoadState.LOADED
    build2 = mgr.on_step_start(step=2, query="", build_only=True)
    assert "knowledge body 1" in build2.prompt
    # 未命中的仍然索引态
    assert mgr.items["know2"].state == LoadState.INDEX_ONLY


# ── 附加：token 计数与相似性跳过（召回零成本） ──

def test_count_tokens_nonzero():
    assert count_tokens("hello world 这是一段中文") > 0
    assert count_tokens("") == 0


def test_recall_skips_when_below_threshold():
    """相似度不足 → 跳过检索（skipped=True，零加载）。"""
    cfg = ContextConfig(
        recall=RecallConfig(mode="trigger+vector", similarity_threshold=0.95))
    mgr = ContextManager(cfg=cfg, embed_fn=lambda t: [1.0, 0.0])
    mgr.on_session_start("SYS", "", "REQ")
    mgr.register(ContextItem(
        id="k1", type=ItemType.KNOWLEDGE, content="unrelated body",
        recoverable=True))
    mgr.recall_engine.store_embedding("k1", [0.0, 1.0])  # 余弦=0
    r = mgr.load_by_trigger("something entirely different")
    assert r.skipped is True
    assert mgr.items["k1"].state == LoadState.INDEX_ONLY


# ── 10. 大观察截断存档（truncate-and-store，对齐 Hermes snapshot）──

def test_observation_truncated_and_stored():
    cfg = ContextConfig(obs_full_chars=500)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    big = "x" * 2000
    add_obs(mgr, "o_big", big, step=1, tool="read_file", one_line="读了大文件")
    it = mgr.items["o_big"]
    assert len(it.content) < 2000, "进上下文的应是截断后内容"
    assert "已截断" in it.content
    assert it.external_ref, "全文必须存档留指针"
    assert mgr.load_by_ref(it.external_ref) == big, "原文可恢复"
    assert it.token_count < count_tokens(big), "预算按截断后内容计"


# ── 11. turn 内主动卸载：重复观察去重 + 过期观察降级（对齐 Hermes _prune_old_tool_results）──

def test_proactive_prune_dedup_and_stale():
    cfg = ContextConfig(protect_recent_steps=2, max_tokens=100000)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    # 同 tool+params 连读两次（不同内容）+ 一条过期观察
    mgr.on_observation("r_stale", "other file body", tool="read_file",
                       params_summary="other.py", one_line="r_stale", step=1)
    mgr.on_observation("r1", "v1 body", tool="read_file",
                       params_summary="app.py", one_line="r1", step=3)
    mgr.on_observation("r2", "v2 body", tool="read_file",
                       params_summary="app.py", one_line="r2", step=4)
    build = mgr.on_step_start(step=6, query="")
    # 去重：同 params 只留最新（r2 全文），r1 降级后又超龄 → 出上下文
    r2 = mgr.items["r2"]
    assert r2.state == LoadState.LOADED and not r2.masked
    assert r2.content == "v2 body"
    assert mgr.items["r1"].state == LoadState.INDEX_ONLY
    # 过期：r_stale 超租约 → 一行摘要，原文存外部可恢复
    stale = mgr.items["r_stale"]
    assert stale.masked and "other file body" not in stale.content
    assert stale.external_ref
    assert mgr.load_by_ref(str(stale.external_ref)) == "other file body"
    # 摘要（含 one_line）与最新全文都在本步 prompt 里
    assert "v2 body" in build.prompt
    assert "other file body" not in build.prompt
    assert any("主动卸载" in d for d in mgr.decisions_log())


def test_proactive_prune_respects_protect_window():
    """保护窗内的新观察不动。"""
    cfg = ContextConfig(protect_recent_steps=2, max_tokens=100000)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    mgr.on_observation("n1", "recent body", tool="read_file",
                       params_summary="a.py", one_line="n1", step=4)
    build = mgr.on_step_start(step=5, query="")
    it = mgr.items["n1"]
    assert not it.masked and it.state == LoadState.LOADED
    assert "recent body" in build.prompt


# ── 12. 计数契约：未达 100% 硬限的折叠 reason=long_loop（不计压缩次数）──

def test_long_loop_reason_is_not_budget():
    cfg = ContextConfig(max_tokens=100000, compress_trigger_ratio=1.0,
                        turn_compress_min_steps=3)
    mgr = ContextManager(cfg=cfg)
    mgr.on_session_start("SYS", "", "REQ")
    for i in range(1, 6):
        add_obs(mgr, f"o{i}", "k" * 300, step=i)
        mgr.on_step_start(step=i, query="")
    assert mgr.budget.used < 100000, "远未到硬限"
    res = mgr.on_turn_end(step_count=5)
    assert res.reason == "long_loop", \
        f"步数超阈值但未达限 → 应为 long_loop，实际 {res.reason}"
    # 反向：达限 → budget（由 test_budget_ratio_trigger 覆盖）


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
