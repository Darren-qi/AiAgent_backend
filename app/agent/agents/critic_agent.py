"""批评 Agent"""

import json
import logging
from typing import Dict, Any, Optional

from app.agent.agents.base import BaseAgent, AgentType, AgentResult

logger = logging.getLogger(__name__)


class CriticAgent(BaseAgent):
    """批评 Agent - 负责审查和评估执行结果"""

    def __init__(self, **kwargs):
        super().__init__(agent_type=AgentType.CRITIC, name="CriticAgent", **kwargs)
        self.min_quality_score = 0.6

    def _get_default_system_prompt(self) -> str:
        return """你是一个任务质量审查专家。你的职责是评估任务执行结果的质量，并决定是否需要重新执行。

评估标准：
1. 结果是否满足用户原始需求
2. 结果的准确性和完整性
3. 是否存在明显错误或遗漏
4. 输出格式是否符合要求

输出格式（JSON）：
{
    "quality_score": 0.0-1.0,  // 质量评分
    "is_acceptable": true/false,  // 是否可接受
    "issues": ["问题1", "问题2"],  // 发现的问题
    "suggestions": ["建议1", "建议2"],  // 改进建议
    "needs_replan": true/false  // 是否需要重新规划
}"""

    async def run(
        self,
        task: str,
        results: list,
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResult:
        """审查执行结果"""
        logger.info(f"[CriticAgent] 开始审查 {len(results)} 个执行结果")
        context = context or {}

        # 构建审查上下文
        results_summary = self._summarize_results(results)

        prompt = f"""{self.system_prompt}

原始任务：
{task}

执行结果摘要：
{results_summary}

请评估结果质量："""

        try:
            response = await self._call_llm(
                prompt=prompt,
                temperature=0.2,
                max_tokens=1000,
                strategy="quality"
            )

            evaluation = self._parse_evaluation(response)
            if not evaluation:
                return AgentResult(
                    success=False,
                    error="无法解析评估结果"
                )

            quality_score = evaluation.get("quality_score", 0)
            needs_replan = evaluation.get("needs_replan", False) or quality_score < self.min_quality_score

            logger.info(f"[CriticAgent] 评估完成 - 质量评分: {quality_score:.2f}, 需要重规划: {needs_replan}")

            return AgentResult(
                success=True,
                data=evaluation,
                metadata={
                    "quality_score": quality_score,
                    "needs_replan": needs_replan,
                    "results_count": len(results)
                }
            )
        except Exception as e:
            logger.error(f"[CriticAgent] 审查失败: {e}")
            return AgentResult(success=False, error=str(e))

    def _summarize_results(self, results: list) -> str:
        """生成结果摘要"""
        summary_parts = []
        for i, result in enumerate(results, 1):
            desc = result.get("description", f"任务 {i}")
            success = result.get("success", False)
            data = result.get("data", {})
            error = result.get("error")

            if success:
                data_str = str(data)[:200] if data else "无数据"
                summary_parts.append(f"任务 {i} ({desc}): 成功 - {data_str}")
            else:
                summary_parts.append(f"任务 {i} ({desc}): 失败 - {error}")

        return "\n".join(summary_parts)

    def _parse_evaluation(self, response: str) -> Optional[Dict[str, Any]]:
        """解析评估结果"""
        import re
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                evaluation = json.loads(json_match.group())
                return evaluation
        except Exception as e:
            logger.warning(f"[CriticAgent] 解析评估结果失败: {e}")

        return None
