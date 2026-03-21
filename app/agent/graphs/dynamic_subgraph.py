"""动态子图"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class SubgraphState:
    """子图状态"""
    task_id: str
    parent_step: int
    sub_steps: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


class DynamicSubgraph:
    """
    动态子图

    根据主图规划，动态创建并执行子任务图。
    支持并行和串行两种执行模式。
    """

    def __init__(self):
        self.nodes = {}

    async def execute(
        self,
        steps: List[Dict[str, Any]],
        mode: str = "sequential",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行子图

        Args:
            steps: 子步骤列表
            mode: 执行模式，sequential(串行) 或 parallel(并行)
            context: 执行上下文

        Returns:
            包含 results 和 error 的字典
        """
        if mode == "parallel":
            return await self._execute_parallel(steps, context)
        else:
            return await self._execute_sequential(steps, context)

    async def _execute_sequential(
        self,
        steps: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """串行执行"""
        results = []
        for step in steps:
            result = await self._execute_single_step(step, context)
            results.append(result)
            if isinstance(result, dict) and not result.get("success", True):
                return {"results": results, "error": result.get("error")}
        return {"results": results, "error": None}

    async def _execute_parallel(
        self,
        steps: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """并行执行"""
        import asyncio
        tasks = [self._execute_single_step(step, context) for step in steps]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                processed_results.append({"success": False, "error": str(result)})
            else:
                processed_results.append(result)
                if isinstance(result, dict) and not result.get("success", True):
                    errors.append(result.get("error"))

        return {
            "results": processed_results,
            "error": "; ".join(errors) if errors else None
        }

    async def _execute_single_step(
        self,
        step: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "unknown")
        params = step.get("params", {})

        try:
            from app.agent.skills.registry import registry
            skill = registry.get(action)

            if skill:
                result = await skill.execute(**params)
                return {
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "action": action,
                }
            else:
                return {
                    "success": False,
                    "error": f"未找到 Skill: {action}",
                    "action": action,
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "action": action,
            }

    def add_node(self, name: str, handler) -> None:
        """添加子图节点"""
        self.nodes[name] = handler

    def get_node(self, name: str):
        """获取子图节点"""
        return self.nodes.get(name)
