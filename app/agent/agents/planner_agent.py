"""规划 Agent"""

import json
import re
import logging
from typing import Dict, Any, Optional, List

from app.agent.agents.base import BaseAgent, AgentType, AgentResult
from app.agent.skills import get_loader

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    """规划 Agent - 负责将复杂任务分解为可执行的子任务"""

    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.PLANNER, name="PlannerAgent", **kwargs)
        self.max_subtasks = 10
        self._skill_loader = get_loader()

    def _get_default_system_prompt(self) -> str:
        return """你是一个专业的任务规划专家。你的职责是将复杂任务分解为可执行的子任务步骤。

工作流程：
1. 分析用户任务，确定需要哪些技能/工具
2. 将任务分解为有序的子任务
3. 识别可以并行执行的子任务
4. 确保子任务之间有明确的数据流动

输出格式：
请返回 JSON 格式的执行计划：
{
    "subtasks": [
        {
            "id": 1,
            "description": "子任务描述",
            "skill": "使用的技能名称",
            "params": {"参数": "值"},
            "parallel_with": [],  // 可并行执行的任务ID列表
            "depends_on": []      // 依赖的任务ID列表
        }
    ],
    "reasoning": "规划理由"
}"""

    async def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """执行任务规划"""
        logger.info(f"[PlannerAgent] 开始规划任务: {task[:80]}...")
        context = context or {}

        # 构建 Skill 清单
        skill_list = self._build_skill_list()

        # 构建提示词
        prompt = f"""{self.system_prompt}

可用技能清单：
{skill_list}

历史上下文：
{context.get("history_summary", "无")}

待规划任务：
{task}

请生成执行计划："""

        try:
            response = await self._call_llm(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000,
                strategy="quality"
            )

            plan = self._parse_plan(response)
            if not plan:
                return AgentResult(
                    success=False,
                    error="无法解析规划结果"
                )

            logger.info(f"[PlannerAgent] 规划完成，生成 {len(plan.get('subtasks', []))} 个子任务")

            return AgentResult(
                success=True,
                data=plan,
                metadata={"task": task, "subtask_count": len(plan.get("subtasks", []))}
            )
        except Exception as e:
            logger.error(f"[PlannerAgent] 规划失败: {e}")
            return AgentResult(success=False, error=str(e))

    def _build_skill_list(self) -> str:
        """构建 Skill 清单（从 SKILL.md 动态加载）"""
        schemas = self._skill_loader.get_schemas()
        if not schemas:
            return "无可用技能"

        lines = []
        for schema in schemas:
            params = schema.get("parameters", {})
            if isinstance(params, dict):
                prop_names = list(params.get("properties", {}).keys())
            elif isinstance(params, list):
                prop_names = [p.get("name", "") for p in params]
            else:
                prop_names = []

            params_str = ", ".join(prop_names) if prop_names else "无"
            lines.append(f"- {schema['name']}: {schema['description']} | 参数: {params_str}")
        return "\n".join(lines)

    def _parse_plan(self, response: str) -> Optional[Dict[str, Any]]:
        """解析规划结果"""
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.warning(f"[PlannerAgent] 解析规划失败: {e}")

        return None
