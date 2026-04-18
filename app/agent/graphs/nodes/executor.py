"""执行器节点"""

from typing import Any, Dict, Optional

from app.agent.skills.core.progressive_loader import get_loader


class Executor:
    """任务执行器（支持新旧 Skill 结构）"""

    def __init__(self):
        self._loader = get_loader()

    async def execute_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action")
        params = step.get("params", {})

        # 尝试从新加载器执行
        try:
            result = await self._loader.execute(action, params)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
            }
        except Exception as e:
            # 备用：尝试从旧 registry 执行
            try:
                from app.agent.skills.registry import registry
                skill = registry.get(action)
                if skill:
                    result = await skill.execute(**params)
                    return {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                    }
            except:
                pass

            return {"success": False, "error": f"执行 Skill '{action}' 失败: {e}"}

    async def execute_plan(self, plan: list) -> list:
        """执行完整计划"""
        results = []
        for step in plan:
            result = await self.execute_step(step)
            results.append(result)
            if not result.get("success"):
                break
        return results
