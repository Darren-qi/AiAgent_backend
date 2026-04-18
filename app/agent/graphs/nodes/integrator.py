"""
结果整合节点
"""

import logging
from typing import TYPE_CHECKING, Dict, Any, List, Optional

if TYPE_CHECKING:
    from app.agent.graphs.main_graph import AgentState

logger = logging.getLogger(__name__)

# 完成总结 Prompt
COMPLETION_SUMMARY_PROMPT = """你是任务执行总结专家。请为以下任务执行生成完成总结。

## 用户任务
{task}

## 待办执行结果
{results}

## 输出要求
请按以下格式生成总结：

### 实现内容
- 列出完成的主要功能/工作

### 执行效果
- 描述达到的效果
- 如有数据，说明关键指标

### 建议下一步
- 基于当前任务，推荐 2-3 个合理的后续操作
- 用简洁的语言描述

请生成总结："""


class Integrator:
    """结果整合器"""

    def __init__(self):
        self._llm_factory = None
        self._task_id: Optional[str] = None

    def set_task_id(self, task_id: str) -> None:
        """设置任务 ID，用于可取消的 LLM 调用"""
        self._task_id = task_id

    @property
    def llm_factory(self):
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            from app.agent.llm.factory import LLMFactory
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    async def _llm_chat(self, messages: list, **kwargs):
        """统一 LLM 调用方法，自动传递 task_id 以支持取消"""
        if self._task_id:
            kwargs["task_id"] = self._task_id
        return await self.llm_factory.chat(messages, **kwargs)

    async def integrate(self, state: "AgentState") -> str:
        """
        整合执行结果，生成最终响应

        将多个子任务的结果整合为一个连贯的响应。
        """
        results = state.results
        if not results:
            return "任务已完成，但没有返回结果。"

        if len(results) == 1:
            return self._format_single_result(results[0])

        return self._format_multiple_results(results)

    def _format_single_result(self, result: Any) -> str:
        if isinstance(result, dict):
            if "content" in result:
                return str(result["content"])
            return str(result)
        return str(result)

    def _format_multiple_results(self, results: List[Any]) -> str:
        parts = []
        for i, result in enumerate(results, 1):
            if isinstance(result, dict):
                content = result.get("content", result.get("output", str(result)))
            else:
                content = str(result)
            parts.append(f"步骤 {i}: {content}")

        return "\n\n".join(parts)

    async def summarize(self, results: List[Any], task: str) -> str:
        """
        对结果进行摘要

        将大量结果压缩为简洁的摘要。
        """
        if not results:
            return "无结果"

        if len(results) <= 3:
            from app.agent.graphs.main_graph import AgentState
            return await self.integrate(AgentState(messages=[], task=task, results=results))

        summary_parts = []
        for i, result in enumerate(results[:3], 1):
            if isinstance(result, dict):
                content = result.get("content", str(result))
            else:
                content = str(result)
            summary_parts.append(f"结果 {i}: {content[:200]}")

        return "\n\n".join(summary_parts) + f"\n\n... 共 {len(results)} 个结果"

    async def generate_completion_summary(
        self,
        task: str,
        todos: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        生成任务完成总结

        Args:
            task: 用户原始任务
            todos: 待办列表
            results: 执行结果

        Returns:
            总结字典 {summary, suggestions}
        """
        logger.info("[Integrator] 生成完成总结")

        # 格式化结果
        results_str = self._format_todos_results(todos, results)

        # 尝试使用 LLM 生成总结
        if self._llm_factory:
            try:
                prompt = COMPLETION_SUMMARY_PROMPT.format(
                    task=task,
                    results=results_str
                )

                response = await self._llm_chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=None,
                    strategy="quality",
                    temperature=0.3,
                    max_tokens=1000,
                )

                summary = response.content.strip()
                suggestions = self._extract_suggestions(summary)

                return {
                    "summary": summary,
                    "suggestions": suggestions,
                    "success": True
                }
            except Exception as e:
                logger.warning(f"[Integrator] LLM 总结生成失败: {e}")

        # 降级：生成简单总结
        return self._generate_simple_summary(task, todos, results)

    def _format_todos_results(
        self,
        todos: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ) -> str:
        """格式化待办和结果"""
        parts = []

        for i, (todo, result) in enumerate(zip(todos, results), 1):
            title = todo.get("title", f"待办 {i}")
            success = result.get("success", False)
            status = "✅ 完成" if success else "❌ 失败"
            summary = result.get("summary", "")

            parts.append(f"待办 {i}: {title}")
            parts.append(f"  状态: {status}")
            if summary:
                parts.append(f"  结果: {summary[:100]}")

        return "\n".join(parts)

    def _extract_suggestions(self, summary: str) -> List[str]:
        """从总结中提取建议"""
        suggestions = []

        # 简单解析 "建议下一步" 部分
        if "建议下一步" in summary:
            section = summary.split("建议下一步")[-1]
            lines = section.split("\n")
            for line in lines:
                line = line.strip()
                if line and (line.startswith("-") or line.startswith("*")):
                    suggestion = line.lstrip("-* ").strip()
                    if suggestion and len(suggestion) > 5:
                        suggestions.append(suggestion)

        return suggestions[:3]  # 最多3条

    def _generate_simple_summary(
        self,
        task: str,
        todos: List[Dict[str, Any]],
        results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """生成简单的总结（降级方案）"""
        completed = sum(1 for r in results if r.get("success", False))
        total = len(results)

        # 生成总结
        summary = f"✅ 任务完成\n\n"
        summary += f"已完成 {completed}/{total} 个待办事项。\n\n"

        for i, (todo, result) in enumerate(zip(todos, results), 1):
            title = todo.get("title", "")
            success = result.get("success", False)
            status = "✅" if success else "❌"
            summary += f"{status} {title}\n"

        # 生成建议
        suggestions = []
        if completed == total:
            suggestions = [
                "添加测试用例验证功能",
                "提交代码到仓库",
                "编写相关文档"
            ]
        else:
            suggestions = [
                "修复失败的待办",
                "调整待办优先级",
                "重新执行任务"
            ]

        return {
            "summary": summary,
            "suggestions": suggestions,
            "success": completed == total
        }
