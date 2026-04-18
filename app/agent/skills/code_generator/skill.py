"""Code Generator Skill - 代码生成器技能"""

import logging
import time
import re
from typing import Dict, Any

from app.agent.skills.core.base_skill import BaseSkill, SkillResult
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class CodeGeneratorSkill(BaseSkill):
    """代码生成 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "language", "type": "string", "required": False, "description": "编程语言", "default": "python"},
        {"name": "requirements", "type": "string", "required": True, "description": "代码需求描述"},
        {"name": "framework", "type": "string", "required": False, "description": "框架"},
        {"name": "task_path", "type": "string", "required": False, "description": "项目路径（可选，用于自动写入文件）"},
    ]

    def __init__(self):
        super().__init__()
        self.name = "code_generator"
        self.description = "生成代码，支持多种编程语言"
        self.parameters = self.DEFAULT_PARAMETERS

    async def execute(self, **kwargs) -> SkillResult:
        requirements = kwargs.get("requirements", "")
        language = kwargs.get("language", "python")
        framework = kwargs.get("framework", "")
        task_path = kwargs.get("task_path")
        session_id = kwargs.get("session_id")

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

            generated_code = response.content

            # 如果有 task_path，自动写入文件
            if task_path:
                write_result = await self._auto_write_files(
                    code=generated_code,
                    task_path=task_path,
                    session_id=session_id,
                    language=language
                )
                if write_result:
                    logger.info(f"[CodeGenerator] 自动写入 {len(write_result)} 个文件")

            return SkillResult(
                success=True,
                data={
                    "language": language,
                    "code": generated_code,
                    "framework": framework,
                },
                metadata={"model": response.model, "provider": response.provider}
            )
        except Exception as e:
            logger.error(f"[CodeGenerator] 生成代码失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _auto_write_files(
        self,
        code: str,
        task_path: str,
        session_id: str,
        language: str
    ) -> list:
        """
        自动将生成的代码写入文件

        解析代码中的文件名注释，将代码写入对应文件
        """
        # 动态导入 file_operations
        try:
            from app.agent.skills.file_operations.skill import FileOperationsSkill
            file_ops = FileOperationsSkill()

            # 初始化会话限制
            if session_id:
                from app.agent.skills.file_operations.skill import get_allowed_project_root
                file_ops._allowed_project_root = await get_allowed_project_root(session_id)

            written_files = []

            # 尝试从代码中提取文件名
            # 常见模式：# file: xxx.py 或 # filename: xxx.py
            filename_patterns = [
                r'[#\s]*(?:file|filename|path)[:\s]+([^\s\n]+)',  # # file: app.py
                r'["\']([a-zA-Z_][\w]*\.(?:py|js|ts|jsx|tsx|html|css|json|yaml|yml|txt))["\']',  # "app.py"
                r'class\s+(\w+)|def\s+(\w+)',  # class X 或 def Y (尝试推断文件名)
            ]

            # 尝试提取代码块中的文件名
            # 格式: ```python app.py
            code_block_match = re.search(r'```(?:\w+)?\s*(\S+\.(?:py|js|ts|jsx|tsx|html|css|json|yaml|yml|txt))\s*\n', code, re.IGNORECASE)
            if code_block_match:
                filename = code_block_match.group(1)
            else:
                # 尝试从第一行代码推断
                filename = self._extract_filename_from_code(code, language)

            if filename:
                # 写入文件
                result = await file_ops.execute(
                    operation="write",
                    path=filename,
                    content=code,
                    task_path=task_path,
                    session_id=session_id
                )
                if result.success:
                    written_files.append(filename)

            return written_files

        except Exception as e:
            logger.warning(f"[CodeGenerator] 自动写入文件失败: {e}")
            return []

    def _extract_filename_from_code(self, code: str, language: str) -> str:
        """从代码内容推断文件名"""
        # 语言到文件扩展名的映射
        ext_map = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "html": "html",
            "css": "css",
            "json": "json",
            "yaml": "yaml",
        }

        ext = ext_map.get(language.lower(), "txt")

        # 尝试从代码中提取类名或函数名
        class_match = re.search(r'class\s+(\w+)', code)
        if class_match:
            class_name = class_match.group(1)
            # 转换为 snake_case
            import re
            snake_name = re.sub(r'(?<!^)(?=[A-Z])', '_', class_name).lower()
            return f"{snake_name}.{ext}"

        func_match = re.search(r'def\s+(\w+)', code)
        if func_match:
            func_name = func_match.group(1)
            return f"{func_name}.{ext}"

        # 默认文件名
        default_names = {
            "python": "app.py",
            "javascript": "app.js",
            "typescript": "app.ts",
            "html": "index.html",
            "css": "style.css",
            "json": "config.json",
        }
        return default_names.get(language.lower(), f"generated.{ext}")

    def _build_prompt(self, requirements: str, language: str, framework: str) -> str:
        framework_hint = f"，使用 {framework} 框架" if framework else ""
        timestamp = int(time.time() * 1000)

        return f"""你是一个专业的代码生成专家。请根据以下需求生成高质量代码。

## 基本信息
- 编程语言：{language}{framework_hint}
- 时间戳：{timestamp}（用于生成唯一项目标识）

## 需求描述
{requirements}

## 文件输出规则（必须严格遵守）
1. **重要**：不要在文件路径中写项目文件夹名！系统会自动添加！
   - 错误：`../tasks/blog_system_{timestamp}/app.py`（包含项目名）
   - 正确：`app.py`（只写相对于项目根目录的路径）
   - 正确：`templates/base.html`
   - 正确：`static/css/style.css`
2. **所有文件路径都是相对于项目根目录的**
3. **严格禁止**：
   - 禁止在 backend/ 或其子目录下创建文件
   - 禁止使用绝对路径

## 代码质量要求
- 代码简洁、规范、可直接运行
- 包含必要的注释说明
- 错误处理完善
- 遵循该语言的代码规范

## 输出要求
请直接返回生成的代码。文件路径在代码注释中标明。
"""


# 导出执行入口
skill = CodeGeneratorSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
