"""观察结果解析专项测试：完成状态只认"完成状态:"行，原因文本不得污染判定

背景（2026-11-13 生产 task82 假完成取证）：
观察输出 "完成状态: 未完成\n原因: 本轮动作已完成，但根目录仍残留..." 时，
旧逻辑按全文子串判定 "已完成" in content → completed=True，待办被打勾。
"""

from app.agent.graphs.nodes.planner import Planner


def _parse(content: str) -> dict:
    return Planner._parse_observation_response(None, content)


class TestParseObservationStatus:

    def test_observe_tool_failure_fast_path_no_llm(self):
        """工具执行失败 → observe 快路径直接返回错误反馈（不调 LLM），
        内含错误原文+「调整参数重试」，供下一轮 ReAct 修正参数重试。
        2026-11-13 用户测试现场：edit 发 edits 数组报"缺少 old_text"，
        该反馈链路必须存在且带错误细节。"""
        import asyncio
        p = Planner()
        obs = asyncio.run(p.observe(
            task="搭建 Flask 项目",
            todo={"id": 5, "title": "添加表单校验"},
            action="file_operations",
            params={"operation": "edit", "edits": []},
            result={"success": False,
                    "error": "缺少 old_text 参数（待替换的原文片段，需与文件内容逐字一致）"},
        ))
        assert obs["completed"] is False
        assert obs["success"] is False
        assert "工具执行失败" in obs["reason"]
        assert "缺少 old_text" in obs["reason"], "反馈必须携带错误原文"
        assert obs["suggestion"] == "调整参数重试"


    def test_status_line_not_completed(self):
        content = (
            "完成状态: 未完成\n"
            "原因: 本轮成功写入 backend/main.py，但根目录仍残留 main.py 等文件，迁移未完成\n"
            "建议: 继续迁移剩余文件"
        )
        r = _parse(content)
        assert r["completed"] is False, f"原因含'已完成'字样被误判成完成: {r}"
        assert r["success"] is False
        assert "残留" in r["reason"]

    def test_status_line_completed(self):
        content = "完成状态: 已完成\n原因: 三个文件已全部搬入 backend\n建议: 无"
        r = _parse(content)
        assert r["completed"] is True
        assert r["success"] is True

    def test_partial_completed(self):
        content = "完成状态: 部分完成\n原因: 已完成 2/3 文件\n建议: 继续"
        r = _parse(content)
        assert r["completed"] is True

    def test_reason_with_partial_phrase_not_polluting(self):
        """状态行之外出现'部分完成'字样不应影响判定（只认状态行）"""
        content = "完成状态: 未完成\n原因: 上一轮部分完成，本轮工具失败\n建议: 重试"
        r = _parse(content)
        assert r["completed"] is False

    def test_fallback_without_status_line(self):
        """无状态行时退回旧行为（全文判定），不比旧逻辑更糟"""
        r = _parse("原因: 已完成全部目标")
        assert r["completed"] is True

    def test_no_status_no_completion_claim(self):
        r = _parse("原因: 需要继续收集信息")
        assert r["completed"] is False
