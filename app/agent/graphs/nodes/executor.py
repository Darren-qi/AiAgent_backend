"""执行器节点"""

from typing import Any, Dict, Optional

from app.agent.skills.registry import registry


class Executor:
    """任务执行器"""

    def __init__(self):
        self._skill_registry = registry

    async def execute_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action")
        params = step.get("params", {})

        skill = self._skill_registry.get(action)
        if not skill:
            return {"success": False, "error": f"未找到 Skill: {action}"}

        result = await skill.execute(**params)

        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
        }

    async def execute_plan(self, plan: list) -> list:
        """执行完整计划"""
        results = []
        for step in plan:
            result = await self.execute_step(step)
            results.append(result)
            if not result.get("success"):
                break
        return results
