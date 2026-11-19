"""Code Generator Skill - 代码生成器技能"""

import logging
import re
import time

from app.agent.llm.factory import LLMFactory
from app.agent.skills.core.base_skill import BaseSkill, SkillResult

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
                # 多文件项目 3000 token 会硬截断，后面的文件块静默丢失
                max_tokens=8000,
            )

            generated_code = response.content

            # 无条件写入：task_path 为空时 file_operations 会自动建
            # auto_project_<ts> 目录（与 read/write 自己的兜底一致）。
            # 原来的 `if task_path:` 在新会话（内存里还没有 task_path）会直接
            # 跳过写入却返回 success=True —— 待办显示"已完成"但磁盘零文件。
            write_result = await self._auto_write_files(
                code=generated_code,
                task_path=task_path or "",
                session_id=session_id or "",
                language=language
            )
            written_files = write_result.get("files") or []
            written_project = write_result.get("project")

            if written_files:
                logger.info(f"[CodeGenerator] 自动写入 {len(written_files)} 个文件")
            else:
                # 一个文件都没落盘就不能算成功，否则上层显示"已完成"是假的
                logger.warning("[CodeGenerator] 未写入任何文件（代码块为空或写入失败）")
                return SkillResult(
                    success=False,
                    error="代码已生成但未写入任何文件",
                    data={"language": language, "code": generated_code,
                          "framework": framework},
                )

            return SkillResult(
                success=True,
                data={
                    "language": language,
                    "code": generated_code,
                    "framework": framework,
                    "written_files": written_files,
                    # main_graph 靠它更新 task_path 并推送文件树
                    "project_name": written_project,
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
    ) -> dict:
        """
        自动将生成的代码写入文件

        支持两种格式：
        1. 多文件格式：```python filename.py ... ``` 分隔的代码块
        2. 单文件格式：整个代码写入一个文件

        Returns:
            {"files": [写入的文件名], "project": 实际落地的目录名或 None}
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
            written_project = None  # 实际落地的目录，供同会话后续待办复用

            # 尝试提取多文件代码块
            # 格式: ```python filename.py ... ```
            code_block_pattern = r'```(?:python|javascript|typescript|html|css|json|yaml|yml)?\s*(\S+\.(?:py|js|ts|jsx|tsx|html|css|json|yaml|yml|txt))\s*\n(.*?)```'
            code_blocks = re.findall(code_block_pattern, code, re.DOTALL | re.IGNORECASE)

            if code_blocks:
                # 多文件模式
                for filename, content in code_blocks:
                    # 清理内容
                    content = content.strip()
                    if not content:
                        continue

                    # 写入文件
                    result = await file_ops.execute(
                        operation="write",
                        path=filename,
                        content=content,
                        task_path=task_path,
                        session_id=session_id
                    )
                    if result.success:
                        written_files.append(filename)
                        written_project = self._pick_project(result, written_project)
                        logger.info(f"[CodeGenerator] 写入文件: {filename}")
            else:
                # 单文件模式：尝试从代码推断文件名
                filename = self._extract_filename_from_code(code, language)
                if filename:
                    result = await file_ops.execute(
                        operation="write",
                        path=filename,
                        content=code,
                        task_path=task_path,
                        session_id=session_id
                    )
                    if result.success:
                        written_files.append(filename)
                        written_project = self._pick_project(result, written_project)
                        logger.info(f"[CodeGenerator] 写入文件: {filename}")

            # 同步任务目录：不写的话，同一会话的后续待办读不到 task_path，
            # 每个待办都会各自新建 auto_project_* 目录，文件散落、互相读不到
            if written_files and written_project:
                await self._sync_task_path(session_id, written_project)

            return {"files": written_files, "project": written_project}

        except Exception as e:
            logger.warning(f"[CodeGenerator] 自动写入文件失败: {e}")
            return {"files": [], "project": None}

    @staticmethod
    def _pick_project(result, current):
        """从 file_operations 结果里取实际落地的目录名（取最新非空的）"""
        data = getattr(result, "data", None)
        if isinstance(data, dict):
            name = data.get("project_name") or data.get("project")
            if name:
                return name
        return current

    @staticmethod
    async def _sync_task_path(session_id, project_name):
        """把任务目录同步给同会话的后续待办（内存 + DB 双写）"""
        if not session_id or not project_name:
            return
        try:
            from app.api.v1.endpoints.agent import session_task_paths
            session_task_paths[session_id] = project_name
        except Exception as e:
            logger.debug(f"[CodeGenerator] 同步内存 task_path 失败: {e}")
        try:
            from app.agent.tools.session_context import set_session_context
            await set_session_context(session_id, "task_path", project_name)
        except Exception as e:
            logger.warning(f"[CodeGenerator] 同步 DB task_path 失败: {e}")

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

## 输出格式（必须严格遵守）
如果需要生成多个文件，必须使用以下格式：

```python app.py
# 文件内容
```

```python models.py
# 文件内容
```

```html templates/base.html
<!-- 文件内容 -->
```

```css static/css/style.css
/* 文件内容 */
```

**重要**：每个代码块必须以 ```语言 文件名 开头，以 ``` 结尾。

## 代码质量要求
- 代码简洁、规范、可直接运行
- 包含必要的注释说明
- 错误处理完善
- 遵循该语言的代码规范

## 输出要求
请直接返回生成的代码，使用上述多文件格式。每个文件用代码块分隔，文件名在代码块开头标明。
"""


# 导出执行入口
skill = CodeGeneratorSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
