"""THOUGHT 提示词关键规则回归（2026-11-13 任务93重构取证后新增）。

规则是行为的载体：规则被误删/改写会静默复发生产问题——
批量 move 不收、路径臆测、归类后误报缺失、凭计划宣布完成。
"""

from app.agent.graphs.nodes.planner import THOUGHT_PROMPT


def test_thought_rules_present():
    # 规则9：批量移动 files 数组（THOUGHT 经 .format()，源码里是双括号转义）
    assert "files=[{{path,dest}}]" in THOUGHT_PROMPT
    # 规则10：清单过期先 list 真实目录树，禁止臆测目录
    assert "看一次真实目录树" in THOUGHT_PROMPT
    # 规则11：失败后修正参数重试同一动作（不许只读绕圈）
    assert "重试同一个动作" in THOUGHT_PROMPT
    # 规则12：结构要求收尾前 list 核对，禁止凭记忆宣布达成
    assert "收尾前必须 operation=list" in THOUGHT_PROMPT
    # 规则13：新建文件写完不读回确认，直接看缺件清单推进（2026-11-13 用户
    # 反馈"读一次写一次总交替"——写后读回是浪费轮次）
    assert "不要读回确认" in THOUGHT_PROMPT


def test_thought_prompt_format_safe():
    """THOUGHT_PROMPT 必须能 format：规则里裸花括号会 KeyError。

    同一坑已复发两次（JSON 示例 {operation}、批量 files={path,dest}），
    任何新规则带花括号必须写 {{}} 转义，此测试兜底。
    """
    out = THOUGHT_PROMPT.format(task="t", todo_id=1, title="x", context="c")
    # 源码写 {{path,dest}}，format 后模型看到单括号 {path,dest}
    assert "files=[{path,dest}]" in out, "转义后模型应看到单括号示例"
