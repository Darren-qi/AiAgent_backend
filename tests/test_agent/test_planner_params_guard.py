"""参数结构崩坏防线（TC-S16-04 配套，2026-11-14 生产取证）。

现场：session_1794668306070 23:00:59-23:06:56 连续 5 次 file_operations
报"缺少 path 参数"（execution_nodes id4672/4788/4792/4796）。

planning 原文显示：模型把大 .vue 文件内容内联进一条参数 JSON，输出结构
崩坏——参数 keys 变成代码碎片（name/component/props/query/...），只剩
尾部 operation/task_path，没有 path。解析器 _extract_json 把它当合法
dict 放行 → 执行必失败，只能靠下一轮 correction 硬救（第 5 次换成
files[] 批量才成功）。

深层原因：SKILL.md 正文传参须知（含"单次批量 ≤4 文件/≤6000 字，超出会
被输出上限截断成残缺 JSON"的同款警告，file_operations/SKILL.md:98）
从未进 prompt——平时只发名称+一句话+tags（progressive_loader.
get_skill_list_str），出错 JIT 也只给 frontmatter schema（无 files/
edits、无批量规模）。

修复（2026-11-14 A+B 已修）：_parse_planning_response 对缺目标参数的
计划标记 params_invalid=True；loader.execute 同样拦截不执行，回注
全量 schema（含 files/edits）+调用须知（渐进第二/三级在错误时注入）。
"""

import pytest

from app.agent.graphs.nodes.planner import Planner

# 生产 id4672 的坏参数原文（planning content 截取，逐字保留）
GARBLED_PARAMS = r'''{"name": "'register'", "component": "() => import('@/views/Register.vue') }\n]\n\nconst router = createRouter({\n  history: createWebHistory()", "props": "true", "meta": "{ requiresAuth: true } }", "query": "{ redirect: to.fullPath } }\n  }\n})\n\nexport default router\n\"}", "operation": "write", "task_path": "auto_project_1794668309"}'''

GARBLED_CONTENT = (
    "动作: file_operations\n"
    f"参数: {GARBLED_PARAMS}\n"
    "原因: \n"
    "修正: 基于错误 '缺少 path 参数' 调整参数"
)

GOOD_CONTENT = (
    "动作: file_operations\n"
    '参数: {"operation": "read", "path": "app/main.py", "task_path": "auto_project_x"}\n'
    "原因: 先读入口文件"
)

# list 无 path 合法，不得误伤
LIST_CONTENT = (
    "动作: file_operations\n"
    '参数: {"operation": "list", "task_path": "auto_project_x"}\n'
    "原因: 看目录结构"
)


def test_garbled_params_rejected():
    p = Planner()
    r = p._parse_planning_response(GARBLED_CONTENT, {"id": 1, "title": "搭前端骨架"})
    assert r.get("params_invalid") is True, (
        f"坏参数被放行（这就是生产5次'缺少 path 参数'的路径）: {r.get('params')}"
    )
    assert "缺少目标参数" in r.get("params_invalid_reason", "")


def test_good_params_not_flagged():
    r = Planner()._parse_planning_response(GOOD_CONTENT, {"id": 1})
    assert not r.get("params_invalid"), "正常带 path 的计划不得被误伤"
    assert r["params"].get("path") == "app/main.py"


def test_list_without_path_not_flagged():
    r = Planner()._parse_planning_response(LIST_CONTENT, {"id": 1})
    assert not r.get("params_invalid"), "operation=list 无 path 是合法形态，不得误伤"


def test_validate_contract_hits_fragment_and_spares_legit():
    from app.agent.skills.core.progressive_loader import validate_params_structure

    # 生产碎片：operation=write 但目标参数全丢 → 拦
    prob = validate_params_structure(
        "file_operations",
        {"operation": "write", "name": "x", "component": "y", "task_path": "t"},
    )
    assert prob and "缺少目标参数" in prob
    # 正常参数（含 main_graph 注入的 task_path/session_id）→ 放行
    assert validate_params_structure(
        "file_operations",
        {"operation": "write", "path": "a.py",
         "task_path": "t", "session_id": "s"},
    ) is None
    # 批量形态 → 放行
    assert validate_params_structure(
        "file_operations",
        {"operation": "edit", "edits": [{"path": "a.py"}]},
    ) is None
    # 未声明契约的 skill / 非 dict → 不误伤或按类型拦
    assert validate_params_structure("no_such_skill", {"foo": 1}) is None
    assert validate_params_structure("file_operations", "raw-string") is not None


async def test_loader_execute_refuses_garbled_params():
    """执行层最后防线：结构崩坏的 params 不进 skill，返回结构化错误。"""
    from app.agent.skills.core.progressive_loader import get_loader

    r = await get_loader().execute(
        "file_operations",
        {"operation": "write", "name": "'register'", "component": "() => import(..)"},
    )
    assert r.success is False
    assert "参数结构异常" in (r.error or "")
    assert "缺少" in (r.error or "")  # 触发 correction 的缺参提示+schema/须知注入


def test_schema_hint_carries_batch_params_and_usage():
    h = Planner()._skill_schema_hint("file_operations")
    assert "files" in h and "edits" in h, "出错 JIT 的 schema 必须含批量参数"
    assert "调用须知" in h, "出错 JIT 必须附带调用须知（渐进第三级）"
    assert "≤4文件" in h
