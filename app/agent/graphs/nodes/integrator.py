"""
结果整合节点
"""

from typing import TYPE_CHECKING, Dict, Any, List

if TYPE_CHECKING:
    from app.agent.graphs.main_graph import AgentState


class Integrator:
    """结果整合器"""

    def __init__(self):
        pass

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
