"""内置 Skill - 代码生成器"""

import logging
from typing import Dict, Any

from app.agent.skills.base import BaseSkill, SkillResult
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class CodeGeneratorSkill(BaseSkill):
    """代码生成 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "code_generator"
        self.description = "生成代码，支持多种编程语言"
        self.parameters = [
            {"name": "language", "type": "string", "required": False, "description": "编程语言 (python/js/ts/go等)"},
            {"name": "requirements", "type": "string", "required": True, "description": "代码需求描述"},
            {"name": "framework", "type": "string", "required": False, "description": "框架 (react/vue/fastapi等)"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        requirements = kwargs.get("requirements", "")
        language = kwargs.get("language", "python")
        framework = kwargs.get("framework", "")

        if not requirements:
            return SkillResult(success=False, error="缺少 requirements 参数")

        prompt = self._build_prompt(requirements, language, framework)

        try:
            llm_factory = LLMFactory.get_instance()
            response = await llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy="quality",
                temperature=0.3,
                max_tokens=3000,
            )

            return SkillResult(
                success=True,
                data={
                    "language": language,
                    "code": response.content,
                    "framework": framework,
                },
                metadata={"model": response.model, "provider": response.provider}
            )
        except Exception as e:
            logger.error(f"[CodeGenerator] 生成代码失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _build_prompt(self, requirements: str, language: str, framework: str) -> str:
        framework_hint = f"，使用 {framework} 框架" if framework else ""
        return f"""请生成 {language} 代码{framework_hint}。

需求描述：
{requirements}

要求：
1. 代码简洁、规范、可直接运行
2. 包含必要的注释说明
3. 错误处理完善
4. 返回纯代码，不需要额外解释
"""
