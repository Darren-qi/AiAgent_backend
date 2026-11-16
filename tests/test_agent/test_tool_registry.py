"""统一注册中心元数据（阶段二，2026-11-16）。

计划 docs/plans/tool-harness-upgrade.md §阶段二：
9 个技能 frontmatter 全字段（risk/path_arg/url_arg/timeout/retry/stage/
operation_targets/usage），核心度量 = operation_targets 覆盖 1/9 → 9/9；
非法 risk/stage 硬拒绝；注册中心查询 API 供阶段三 RunGuard 与阶段四白名单消费。
"""

import pytest

from app.agent.skills.core.progressive_loader import (
    VALID_RISKS,
    VALID_STAGES,
    ProgressiveSkillLoader,
    get_loader,
)

# 内置 9 技能（与 app/agent/skills/ 目录一一对应）
NINE_SKILLS = [
    "code_generator",
    "data_processor",
    "file_operations",
    "general_response",
    "http_client",
    "notification",
    "sandbox",
    "search",
    "search_files",
]


def test_nine_nine_metadata_complete():
    """核心度量：9/9 技能 Harness 元数据齐全（risk/契约/stage/usage）。"""
    loader = get_loader()
    missing = []
    for name in NINE_SKILLS:
        m = loader.get_metadata(name)
        if m is None:
            missing.append(f"{name}: 未注册")
            continue
        if m.risk not in VALID_RISKS:
            missing.append(f"{name}: risk={m.risk!r}")
        if m.stage not in VALID_STAGES:
            missing.append(f"{name}: stage={m.stage!r}")
        if not m.operation_targets:
            missing.append(f"{name}: operation_targets 空")
        if not m.usage:
            missing.append(f"{name}: usage 空")
        if m.timeout < 0 or m.retry < 0:
            missing.append(f"{name}: timeout/retry 非法")
    assert not missing, f"Harness 元数据不完整: {missing}"


def test_operation_targets_star_contract_enforced():
    """'*' 通配契约：无 operation 参数的技能执行前也能拦缺参。"""
    from app.agent.skills.core.progressive_loader import validate_params_structure

    # http_client 缺 url → 拦
    assert validate_params_structure("http_client", {"method": "GET"})
    # 带 url → 放行
    assert validate_params_structure("http_client", {"url": "https://x.com"}) is None
    # search 缺 query → 拦
    assert validate_params_structure("search", {"limit": 5})
    # sandbox code/file 二选一，只给 timeout → 拦
    assert validate_params_structure("sandbox", {"timeout": 30})
    assert validate_params_structure("sandbox", {"code": "print(1)"}) is None
    # file_operations 显式 op 契约不受 "*" 影响
    assert validate_params_structure(
        "file_operations", {"operation": "write", "content": "x"})
    assert validate_params_structure(
        "file_operations",
        {"operation": "write", "path": "a.py", "content": "x"}) is None


def test_invalid_risk_rejected(tmp_path):
    """非法 risk/stage 在解析层硬拒绝（raise → bootstrap 跳过该技能）。"""
    d = tmp_path / "bad_skill"
    d.mkdir()
    md = d / "SKILL.md"
    md.write_text(
        "---\n"
        "name: bad_skill\n"
        "description: x\n"
        "risk: banana\n"
        "parameters:\n"
        "  type: object\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    loader = ProgressiveSkillLoader()
    with pytest.raises(ValueError, match="risk"):
        loader._parse_frontmatter(md, d, is_external=False)

    md.write_text(
        "---\n"
        "name: bad_skill\n"
        "description: x\n"
        "risk: read\n"
        "stage: everywhere\n"
        "parameters:\n"
        "  type: object\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stage"):
        loader._parse_frontmatter(md, d, is_external=False)


def test_missing_risk_and_contract_warns_not_raises(tmp_path, caplog):
    """缺 risk/契约是软约束：warning 不拦（测试断言硬覆盖见上例）。"""
    import logging

    d = tmp_path / "soft_skill"
    d.mkdir()
    md = d / "SKILL.md"
    md.write_text(
        "---\n"
        "name: soft_skill\n"
        "description: x\n"
        "parameters:\n"
        "  type: object\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    loader = ProgressiveSkillLoader()
    with caplog.at_level(logging.WARNING):
        m = loader._parse_frontmatter(md, d, is_external=False)
    assert m.risk == "" and m.stage == "both"
    assert any("缺少 risk" in r.message for r in caplog.records)
    assert any("operation_targets" in r.message for r in caplog.records)


def test_registry_query_apis():
    """注册中心查询 API：get_by_stage / get_by_risk / get_guard_meta。"""
    loader = get_loader()

    # stage：sandbox/notification 只在执行期 → 规划期不可见
    plan_names = {m.name for m in loader.get_by_stage("plan")}
    exec_names = {m.name for m in loader.get_by_stage("execute")}
    assert "sandbox" not in plan_names and "notification" not in plan_names
    assert "sandbox" in exec_names and "notification" in exec_names
    assert "file_operations" in plan_names  # both 技能两边都在

    # risk 分级
    exec_risk = {m.name for m in loader.get_by_risk("exec")}
    assert exec_risk == {"sandbox"}
    net_risk = {m.name for m in loader.get_by_risk("network")}
    assert {"http_client", "notification", "search"} <= net_risk

    # guard 切片
    g = loader.get_guard_meta("file_operations")
    assert g["risk"] == "write" and g["path_arg"] == "path"
    assert g["operation_targets"].get("write")
    assert loader.get_guard_meta("no_such_skill") is None
