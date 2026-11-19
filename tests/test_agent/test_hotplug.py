"""热插拔 + mtime 失效重载（阶段七，2026-11-17）。

计划 tool-harness-upgrade.md §阶段七：
- register_skill_executor 对外 API：运行时注册→可调用
- disable_skill 运行时下架：guard 白名单同步拒（UNKNOWN_SKILL）、prompt 剔除
- _load_module 记 mtime：文件变更即 importlib.reload（改 skill.py 不重启）
"""

import importlib
import os

import pytest

from app.agent.skills.core.base_skill import SkillResult
from app.agent.skills.core.progressive_loader import (
    ProgressiveSkillLoader,
    disable_skill,
    enable_skill,
    get_loader,
    register_skill_executor,
)
from app.agent.skills.guard import tool_guard


@pytest.fixture(autouse=True)
def _clean():
    tool_guard.reset()
    yield
    tool_guard.reset()


async def test_register_executor_hotplug():
    """运行时注册执行器 → 立即可调用（优先于动态模块）。"""
    loader = get_loader()
    calls = {"n": 0}

    async def fake_notification(**kw):
        calls["n"] += 1
        return SkillResult(success=True, data={"sent": True})

    register_skill_executor("notification", fake_notification)
    try:
        r = await loader.execute("notification", {"content": "hi"})
        assert r.success and r.data == {"sent": True}
        assert calls["n"] == 1
    finally:
        loader._executors.pop("notification", None)


async def test_disable_then_unknown_skill():
    """下架 → guard 白名单同步拒绝 UNKNOWN_SKILL、prompt 剔除；恢复后可用。"""
    loader = get_loader()
    assert disable_skill("search") is True
    try:
        # guard 白名单：get_guard_meta 返回 None → begin 拒绝
        assert loader.get_guard_meta("search") is None
        r = await loader.execute("search", {"query": "x"})
        assert r.success is False and r.error_code == "UNKNOWN_SKILL"

        # prompt 注入剔除
        assert "search:" not in get_loader().get_skill_list_str()
        # 查询 API 同步剔除
        assert "search" not in {m.name for m in loader.get_by_risk("network")}
    finally:
        assert enable_skill("search") is True

    # 恢复后守卫放行、prompt 回归
    assert loader.get_guard_meta("search") is not None
    assert "search:" in loader.get_skill_list_str()
    assert tool_guard.begin("search", {"query": "x"}) is None


def test_disable_unknown_name_returns_false():
    assert disable_skill("ghost_xyz") is False
    assert enable_skill("ghost_xyz") is False


def test_mtime_change_triggers_reload(tmp_path, monkeypatch):
    """skill.py mtime 变化 → 下次 _load_module 走 importlib.reload。"""
    # 独立 loader 实例（不污染全局缓存），索引里塞一个可重载的技能
    loader = ProgressiveSkillLoader(skills_root=tmp_path)
    # 用真实 search 技能的元数据结构：直接手工登记索引 + 指向真实文件
    real_meta = get_loader().get_metadata("search")
    assert real_meta is not None
    loader._index["search"] = real_meta

    reload_calls = {"n": 0}
    real_reload = importlib.reload

    def spy_reload(mod):
        reload_calls["n"] += 1
        return real_reload(mod)

    monkeypatch.setattr(importlib, "reload", spy_reload)

    skill_file = real_meta.skill_dir / "skill.py"
    st = skill_file.stat()
    try:
        # 首次加载：记录 mtime、不触发 reload
        m1 = loader._load_module("search")
        assert m1 is not None and reload_calls["n"] == 0
        assert "search" in loader._module_mtimes

        # 把 mtime 推到未来（不改文件内容，测试后还原）
        os.utime(skill_file, (st.st_atime + 10, st.st_mtime + 10))
        m2 = loader._load_module("search")
        assert m2 is not None
        assert reload_calls["n"] == 1, "mtime 变化必须触发一次 reload"
        assert loader._module_mtimes["search"] == skill_file.stat().st_mtime

        # mtime 未再变 → 直接命中缓存，不再 reload
        m3 = loader._load_module("search")
        assert m3 is m2 and reload_calls["n"] == 1
    finally:
        os.utime(skill_file, (st.st_atime, st.st_mtime))  # 还原真实 mtime
        # 还原全局 loader 可能被影响的缓存时间戳
        get_loader()._module_mtimes.pop("search", None)
