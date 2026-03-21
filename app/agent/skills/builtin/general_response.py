"""内置 Skill - 通用响应"""

import logging
from typing import Dict, Any

from app.agent.skills.base import BaseSkill, SkillResult
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class GeneralResponseSkill(BaseSkill):
    """通用对话响应 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "general_response"
        self.description = "通用对话响应，用于问答、解释等"
        self.parameters = [
            {"name": "input", "type": "string", "required": True, "description": "用户输入"},
            {"name": "context", "type": "string", "required": False, "description": "上下文信息"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        user_input = kwargs.get("input", "")
        context = kwargs.get("context", "")

        if not user_input:
            return SkillResult(success=False, error="缺少 input 参数")

        prompt = self._build_prompt(user_input, context)

        try:
            llm_factory = LLMFactory.get_instance()
            response = await llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy="balance",
                temperature=0.7,
                max_tokens=2000,
            )

            return SkillResult(
                success=True,
                data={"response": response.content},
                metadata={"model": response.model, "provider": response.provider}
            )
        except Exception as e:
            logger.error(f"[GeneralResponse] 生成响应失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _build_prompt(self, user_input: str, context: str) -> str:
        if context:
            return f"""上下文信息：
{context}

用户问题：{user_input}

请基于上下文信息，回答用户问题。如需代码示例请提供完整可运行的代码。"""
        return f"""用户问题：{user_input}

请直接回答，不需要额外格式。如果涉及代码请提供完整可运行的示例。"""
