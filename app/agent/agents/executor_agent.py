"""执行 Agent"""

import asyncio
import logging
from typing import Dict, Any, Optional, List

from app.agent.agents.base import BaseAgent, AgentType, AgentResult
from app.agent.skills.core.progressive_loader import get_loader

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """执行 Agent - 负责执行具体的子任务"""

    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.EXECUTOR, name="ExecutorAgent", **kwargs)

    def _get_default_system_prompt(self) -> str:
        return """你是一个任务执行专家。你的职责是执行具体的子任务并返回结果。

工作原则：
1. 严格按照计划执行每个子任务
2. 记录每个步骤的执行结果
3. 如果某步骤失败，报告具体原因
4. 保持结果的可追溯性

你将使用系统中的 Skill 来执行任务，请准确调用并传递参数。"""

    async def run(
        self,
        subtasks: List[Dict[str, Any]],
        mode: str = "sequential",
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """
        执行子任务列表

        Args:
            subtasks: 子任务列表
            mode: 执行模式 - sequential(串行) 或 parallel(并行)
            context: 执行上下文

        Returns:
            AgentResult
        """
        logger.info(f"[ExecutorAgent] 开始执行 {len(subtasks)} 个子任务，模式: {mode}")
        context = context or {}

        results = []
        failed = False
        error_msg = ""

        if mode == "parallel":
            results, failed, error_msg = await self._execute_parallel(subtasks, context)
        else:
            results, failed, error_msg = await self._execute_sequential(subtasks, context)

        return AgentResult(
            success=not failed,
            data={"results": results, "mode": mode},
            error=error_msg if failed else None,
            metadata={
                "total_subtasks": len(subtasks),
                "completed": len([r for r in results if r.get("success")]),
                "failed": len([r for r in results if not r.get("success")])
            }
        )

    async def _execute_sequential(
        self,
        subtasks: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> tuple:
        """串行执行"""
        results = []
        shared_data = {}

        for i, subtask in enumerate(subtasks):
            # 检查依赖是否满足
            depends_on = subtask.get("depends_on", [])
            if depends_on:
                for dep_id in depends_on:
                    if dep_id > i:
                        return results, True, f"循环依赖检测到: 任务 {i+1} 依赖尚未执行的任务 {dep_id}"

            logger.info(f"[ExecutorAgent] 执行子任务 {i+1}/{len(subtasks)}: {subtask.get('description', '')[:50]}...")

            # 填充依赖数据
            params = subtask.get("params", {}).copy()
            params = self._inject_dependencies(params, shared_data)

            result = await self._execute_single(subtask, params)
            results.append({
                "id": subtask.get("id", i+1),
                "description": subtask.get("description", ""),
                "skill": subtask.get("skill", ""),
                **result
            })

            if result.get("success"):
                # 保存结果供后续任务使用
                shared_data[f"task_{subtask.get('id', i+1)}"] = result.get("data")
            else:
                return results, True, f"子任务 {i+1} 执行失败: {result.get('error')}"

        return results, False, ""

    async def _execute_parallel(
        self,
        subtasks: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> tuple:
        """并行执行"""
        # 分离有依赖和无依赖的任务
        independent_tasks = []
        dependent_tasks = []

        for i, subtask in enumerate(subtasks):
            depends_on = subtask.get("depends_on", [])
            if not depends_on:
                independent_tasks.append((i, subtask))
            else:
                dependent_tasks.append((i, subtask))

        results = [None] * len(subtasks)
        shared_data = {}

        # 并行执行无依赖的任务
        if independent_tasks:
            logger.info(f"[ExecutorAgent] 并行执行 {len(independent_tasks)} 个独立任务")
            tasks = []
            for i, subtask in independent_tasks:
                params = subtask.get("params", {}).copy()
                tasks.append(self._execute_single(subtask, params))

            parallel_results = await asyncio.gather(*tasks, return_exceptions=True)

            for idx, (i, subtask), result in zip(range(len(independent_tasks)), independent_tasks, parallel_results):
                if isinstance(result, Exception):
                    result = {"success": False, "error": str(result)}
                results[i] = {
                    "id": subtask.get("id", i+1),
                    "description": subtask.get("description", ""),
                    "skill": subtask.get("skill", ""),
                    **result
                }
                if result.get("success"):
                    shared_data[f"task_{subtask.get('id', i+1)}"] = result.get("data")

        # 串行执行有依赖的任务
        for i, subtask in dependent_tasks:
            depends_on = subtask.get("depends_on", [])
            params = subtask.get("params", {}).copy()
            params = self._inject_dependencies(params, shared_data)

            result = await self._execute_single(subtask, params)
            results[i] = {
                "id": subtask.get("id", i+1),
                "description": subtask.get("description", ""),
                "skill": subtask.get("skill", ""),
                **result
            }

            if result.get("success"):
                shared_data[f"task_{subtask.get('id', i+1)}"] = result.get("data")
            else:
                return results, True, f"子任务 {i+1} 执行失败: {result.get('error')}"

        return results, False, ""

    async def _execute_single(
        self,
        subtask: Dict[str, Any],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行单个子任务"""
        skill_name = subtask.get("skill", "general_response")

        try:
            loader = get_loader()
            result = await loader.execute(skill_name, params)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error
            }
        except Exception as e:
            # 备用：尝试从旧 registry 执行
            try:
                from app.agent.skills.registry import registry
                skill = registry.get(skill_name)
                if skill:
                    result = await skill.execute(**params)
                    return {
                        "success": result.success,
                        "data": result.data,
                        "error": result.error
                    }
            except:
                pass

            logger.error(f"[ExecutorAgent] 执行 Skill '{skill_name}' 失败: {e}")
            return {"success": False, "error": str(e)}

    async def _fallback_to_llm(self, subtask: Dict[str, Any]) -> Dict[str, Any]:
        """当没有对应 Skill 时，使用 LLM 作为后备"""
        description = subtask.get("description", "")
        prompt = f"请完成以下任务：{description}\n\n如果需要代码请提供可运行的代码示例。"

        try:
            response = await self._call_llm(prompt, strategy="quality", temperature=0.3, max_tokens=2000)
            return {
                "success": True,
                "data": {"response": response},
                "error": None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _inject_dependencies(self, params: Dict[str, Any], shared_data: Dict[str, Any]) -> Dict[str, Any]:
        """注入依赖数据到参数中"""
        # 支持通过 ${task_1} 引用前面任务的结果
        for key, value in params.items():
            if isinstance(value, str) and "${task_" in value:
                for data_key, data_value in shared_data.items():
                    value = value.replace(f"${{{data_key}}}", str(data_value))
                params[key] = value
        return params
