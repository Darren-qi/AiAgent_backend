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
        import time
        timestamp = int(time.time() * 1000)

        return f"""你是一个专业的代码生成专家。请根据以下需求生成高质量代码。

## 基本信息
- 编程语言：{language}{framework_hint}
- 时间戳：{timestamp}（用于生成唯一项目标识）

## 需求描述
{requirements}

## 文件输出规则（必须严格遵守，违反将导致系统错误）
1. **重要**：不要在文件路径中写项目文件夹名！系统会自动添加！
   - ❌ 错误：`../tasks/blog_system_{timestamp}/app.py`（包含项目名）
   - ✅ 正确：`app.py`（只写相对于项目根目录的路径）
   - ✅ 正确：`templates/base.html`
   - ✅ 正确：`static/css/style.css`
2. **所有文件路径都是相对于项目根目录的**，不要包含 `blog_system_xxx/` 或类似前缀
3. **严格禁止**：
   - ❌ 禁止在 backend/ 或其子目录下创建文件
   - ❌ 禁止使用绝对路径（如 e:/Projects/AiAgent/backend/...）
   - ❌ 禁止在路径中写项目文件夹名

## 代码质量要求
- 代码简洁、规范、可直接运行
- 包含必要的注释说明
- 错误处理完善
- 遵循该语言的代码规范

## 输出要求
请直接返回生成的代码。文件路径在代码注释中标明。
"""
