"""动态白名单 stage/risk 过滤 + prompt 同步（阶段四，2026-11-17）。

计划 tool-harness-upgrade.md §阶段四：
- 规划早期（stage="plan"）只读集注入，执行期全量——验收：规划期 prompt
  不出现 write/delete 类技能
- tool_deny_risks 风险级黑名单配置位（默认空=行为不变）
- file_operations frontmatter→prompt 参数段试点（唯一权威，防双份漂移）
"""

from app.agent.graphs.nodes.planner import Planner
from app.agent.skills.core.progressive_loader import (
    filter_skills_by_policy,
    get_loader,
)

NINE = {
    "code_generator", "data_processor", "file_operations", "general_response",
    "http_client", "notification", "sandbox", "search", "search_files",
}


def _names(skill_list_str: str) -> set:
    return {
        ln[2:].split(":")[0].strip()
        for ln in skill_list_str.splitlines()
        if ln.startswith("- ")
    }


def test_plan_stage_readonly_set():
    """验收：规划期 prompt 不出现 write/exec/network 类技能，只读集在列。"""
    loader = get_loader()
    plan_names = _names(loader.get_skill_list_str(stage="plan"))
    # write/exec/network 全部不可见
    for excluded in ("file_operations", "sandbox", "notification",
                     "http_client", "search", "code_generator"):
        assert excluded not in plan_names, f"规划期不该出现 {excluded}: {plan_names}"
    # 只读技能可见（risk=read）
    for included in ("data_processor", "general_response", "search_files"):
        assert included in plan_names, f"规划期应保留 {included}: {plan_names}"
    assert plan_names <= NINE


def test_execute_and_default_inject_all():
    """默认（None）与 execute 期全量注入——白名单不误伤现行为。"""
    loader = get_loader()
    assert _names(loader.get_skill_list_str()) == NINE
    assert _names(loader.get_skill_list_str(stage="execute")) == NINE


def test_deny_risks_blacklist(monkeypatch):
    """tool_deny_risks 风险级黑名单：配置生效、默认空不回归。"""
    from app.core.config import get_settings

    loader = get_loader()
    monkeypatch.setattr(get_settings(), "tool_deny_risks", "network,exec")
    denied = _names(loader.get_skill_list_str())
    assert "http_client" not in denied and "search" not in denied
    assert "notification" not in denied and "sandbox" not in denied
    assert "file_operations" in denied  # write 不在本黑名单
    # stage 叠加：plan 只读集再叠黑名单
    plan_denied = _names(loader.get_skill_list_str(stage="plan"))
    assert plan_denied == {"data_processor", "general_response", "search_files"}

    monkeypatch.setattr(get_settings(), "tool_deny_risks", "")
    assert _names(loader.get_skill_list_str()) == NINE


def test_filter_skills_by_policy_pure():
    """纯函数级：stage=None 不做 stage 过滤（风险表"防切断合法规划"）。"""
    loader = get_loader()
    metas = loader.get_all_metadata()
    assert len(filter_skills_by_policy(metas, stage=None)) == 9
    assert len(filter_skills_by_policy(metas, stage="execute")) == 9
    plan_set = filter_skills_by_policy(metas, stage="plan")
    assert all(m.risk == "read" for m in plan_set)
    # deny 单独生效（无 stage）
    net = filter_skills_by_policy(metas, deny_risks={"network"})
    assert "http_client" not in {m.name for m in net}


def test_planner_stage_passthrough():
    """planner 调用点接线：_get_skill_list_str(stage=...) 透传到 loader。"""
    p = Planner()
    plan_names = _names(p._get_skill_list_str(stage="plan"))
    assert "file_operations" not in plan_names
    assert _names(p._get_skill_list_str(stage="execute")) == NINE
    assert _names(p._get_skill_list_str()) == NINE  # 默认不回归


def test_render_skill_params_from_frontmatter():
    """prompt 试点：file_operations 参数段从 frontmatter 渲染，规则不丢。"""
    p = Planner()
    doc = p._render_skill_params("file_operations")
    # 全量参数键（frontmatter 唯一权威）
    for key in ("operation", "path", "content", "files", "edits",
                "old_text", "new_text", "replace_all", "dest"):
        assert key in doc, f"渲染缺参数 {key}: {doc}"
    # usage 规则随渲染进 prompt（原硬编码段的关键约束）
    assert "不能是 Python 代码" in doc
    assert "≤4文件" in doc
    assert "可选值: create, read, write" in doc
    # 未注册技能不炸
    assert p._render_skill_params("no_such_skill") != ""
