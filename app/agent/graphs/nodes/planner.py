"""规划器节点 - LLM 动态规划"""

import asyncio
import json
import re
import logging
from typing import Dict, Any, List, Optional

from app.agent.llm.factory import LLMFactory
from app.agent.skills.core.progressive_loader import get_loader, ProgressiveSkillLoader

logger = logging.getLogger(__name__)

# 快速待办生成 Prompt - 简洁输出，每行 checkbox
QUICK_TODOS_PROMPT = """你是一个任务规划专家。请将用户任务分解为简洁的待办事项。

## 用户任务
{task}

## 输出要求
1. 只输出 2-5 个待办事项，不要太多
2. 每行一个事项，格式: `- [ ] 事项描述`
3. 事项描述要简洁，一行说完
4. 不要详细展开每个步骤的实现细节

## 示例
输入: "为用户模块添加 JWT 认证功能"
输出:
- [ ] 创建 JWT 认证工具类
- [ ] 实现登录接口
- [ ] 添加 Token 验证中间件

输入: "爬取某网站新闻并保存"
输出:
- [ ] 获取网页内容
- [ ] 解析新闻数据
- [ ] 保存到文件

请为以下任务生成待办："""

# 计划分析 Prompt - 对每个计划项进行深入分析
PLAN_ANALYSIS_PROMPT = """你是一个任务执行分析专家。请对以下执行计划中的每个步骤进行深入分析。

## 用户任务
{task}

## 执行计划
{plan}

## 分析要求
对每个步骤，分析以下内容：
1. **步骤目的**：这个步骤要达成什么目标
2. **执行策略**：如何正确执行这个步骤
3. **可能的问题**：执行中可能遇到什么困难
4. **预期结果**：成功执行后的预期产出

## 输出格式
按以下格式输出每个步骤的分析（不需要完整JSON，用简洁的描述性文字）：

**步骤 1: [动作名称]**
- 目的：[分析目的]
- 策略：[执行策略]
- 注意：[需要注意的问题]
- 预期：[预期结果]

请开始分析："""

# Thought 阶段 Prompt - 分析当前状态
THOUGHT_PROMPT = """你正在执行用户任务中的某个待办事项。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 历史上下文
{context}

## 思考要求
1. 分析当前待办的目标
2. 考虑需要的资源和步骤
3. 预判可能的困难
4. 简明输出你的思考

请输出你的思考："""

# Planning 阶段 Prompt - 生成执行计划
PLANNING_PROMPT = """基于你的思考，制定具体的执行动作。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 你的思考
{thought}

## 可用工具
{skill_list}

## 输出要求
1. 选择最合适的工具/动作
2. 给出具体的参数
3. 简洁明了

输出格式：
动作: <action_name>
参数: <具体参数>
原因: <为什么选择这个动作>

请输出："""

# Observation 阶段 Prompt - 验证结果
OBSERVATION_PROMPT = """观察执行结果，判断待办是否完成。

## 用户任务
{task}

## 当前待办
todo_id: {todo_id}
title: {title}

## 执行动作
action: {action}
参数: {params}

## 执行结果
{result}

## 判断要求
1. 结果是否成功？
2. 是否达到预期效果？
3. 是否需要继续或调整？

输出格式：
完成状态: [已完成 / 部分完成 / 未完成]
原因: <判断理由>
建议: <下一步建议>
"""

# Skill 清单（用于规划参考）
AVAILABLE_SKILLS = {
    "http_client": {
        "description": "发起 HTTP/HTTPS 请求，获取网页内容或 API 数据",
        "params": ["url", "method", "headers", "timeout"],
        "use_for": ["爬取网页", "调用API", "获取数据"]
    },
    "code_generator": {
        "description": "生成代码，支持多种编程语言",
        "params": ["language", "requirements", "framework", "task_path"],
        "use_for": ["写代码", "生成代码", "编程"]
    },
    "data_processor": {
        "description": "数据处理、转换、统计分析",
        "params": ["operation", "input_data", "options"],
        "use_for": ["数据处理", "统计分析", "数据转换"]
    },
    # 文件操作（细粒度）
    "init_project": {
        "description": "初始化项目结构 - 创建项目根目录和基础文件框架",
        "params": ["path", "content"],
        "use_for": ["创建项目", "初始化项目", "创建项目结构", "新建项目目录"]
    },
    "write_file": {
        "description": "写入文件 - 创建新文件或覆盖已有文件内容",
        "params": ["path", "content", "task_path"],
        "use_for": ["写文件", "创建文件", "保存文件", "写入代码", "生成模型文件"]
    },
    "read_file": {
        "description": "读取文件 - 查看文件内容",
        "params": ["path"],
        "use_for": ["读取文件", "查看文件", "读取代码"]
    },
    "edit_file": {
        "description": "编辑文件 - 修改已有文件内容（支持增量修改）",
        "params": ["path", "content", "operation"],
        "use_for": ["编辑文件", "修改代码", "更新文件"]
    },
    "delete_file": {
        "description": "删除文件或目录",
        "params": ["path"],
        "use_for": ["删除文件", "删除目录"]
    },
    "list_dir": {
        "description": "列出目录内容",
        "params": ["path"],
        "use_for": ["列出目录", "查看目录"]
    },
    # 兼容旧名称
    "file_operations": {
        "description": "文件操作（通用）- 支持 init_project/write_file/read_file/edit_file/delete_file 等操作",
        "params": ["operation", "path", "content", "task_path"],
        "use_for": ["文件操作", "读写文件"]
    },
    "notification": {
        "description": "发送通知（邮件、社交平台）",
        "params": ["channel", "recipient", "content"],
        "use_for": ["发送通知", "提醒"]
    },
    "search": {
        "description": "信息搜索",
        "params": ["query", "engine", "limit"],
        "use_for": ["搜索信息", "查找资料"]
    },
    "general_response": {
        "description": "通用对话响应",
        "params": [],
        "use_for": ["问答", "对话", "解释"]
    }
}


class Planner:
    """任务规划器 - LLM 动态规划"""

    # 任务规划 Prompt
    PLANNING_PROMPT = """你是一个专业的任务规划专家。请将用户任务分解为可执行的步骤。

## 可用 Skill（工具/动作）：
{skill_list}

## 输出要求：
请以 JSON 数组格式返回执行计划，每个步骤包含：
- **step**: 步骤序号（从1开始）
- **action**: 调用的 Skill 名称（必须在上述列表中）
- **params**: Skill 参数（根据 skill 定义填写）
- **description**: 步骤描述
- **parallel**: 是否可以与后续步骤并行执行
- **depends_on**: 依赖的前置步骤序号列表（默认为空）

## 规则：
1. 独立步骤设置 parallel: true，可并行执行
2. 有依赖的步骤在 depends_on 中指定前置步骤
3. 简单任务 1-3 步，复杂任务 5-10 步
4. 每个步骤必须有实际意义，不能是空步骤
5. 参数必须符合 Skill 定义，不需要的参数可省略
6. 确保步骤之间有明确的数据流动

## 示例：
输入: "爬取某网站新闻并保存到文件"
输出:
[
  {{
    "step": 1,
    "action": "http_client",
    "params": {{"url": "目标URL", "method": "GET"}},
    "description": "获取网页内容",
    "parallel": false,
    "depends_on": []
  }},
  {{
    "step": 2,
    "action": "data_processor",
    "params": {{"operation": "parse_html", "input": "步骤1的结果"}},
    "description": "解析HTML提取新闻标题",
    "parallel": false,
    "depends_on": [1]
  }},
  {{
    "step": 3,
    "action": "file_operations",
    "params": {{"operation": "write", "path": "news.txt", "content": "步骤2的结果"}},
    "description": "保存到文件",
    "parallel": false,
    "depends_on": [2]
  }}
]

请为以下任务制定执行计划："""

    # 计划优化 Prompt（用于 refine）
    REFINE_PROMPT = """你是一个任务规划优化专家。请根据反馈优化执行计划。

## 当前计划：
{current_plan}

## 用户反馈/错误：
{feedback}

## 输出要求：
返回优化后的 JSON 执行计划，格式同上。

请优化计划："""

    def __init__(self):
        self._llm_factory: Optional[LLMFactory] = None
        self._use_llm = True
        self._task_id: Optional[str] = None
        self._fallback_intents = {
            "crawler": ["http_client", "data_processor"],
            "code": ["code_generator"],
            "analysis": ["data_processor", "general_response"],
            "search": ["search"],
            "notification": ["notification"],
            "file_ops": ["file_operations"],
            "data": ["data_processor"],
            "general": ["general_response"],
        }

    def set_task_id(self, task_id: str) -> None:
        """设置任务 ID，用于可取消的 LLM 调用"""
        self._task_id = task_id

    @property
    def llm_factory(self) -> LLMFactory:
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    def _get_skill_list_str(self) -> str:
        """生成 Skill 列表字符串（从渐进式加载器获取）"""
        try:
            loader = get_loader()
            return loader.get_skill_list_str()
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill 列表失败: {e}，使用备用方案")
            # 备用：使用 AVAILABLE_SKILLS
            lines = []
            for name, info in AVAILABLE_SKILLS.items():
                params = ", ".join(info["params"]) if info["params"] else "无"
                use_for = ", ".join(info["use_for"])
                lines.append(f"- **{name}**: {info['description']} | 参数: {params} | 适用: {use_for}")
            return "\n".join(lines)

    async def _llm_chat(self, messages: list, **kwargs):
        """
        统一 LLM 调用方法，自动传递 task_id 以支持取消

        Args:
            messages: 消息列表
            **kwargs: 其他参数（如 strategy, temperature 等）

        Returns:
            LLM 响应
        """
        # 如果有 task_id，传递它以支持可取消的 LLM 调用
        if self._task_id:
            kwargs["task_id"] = self._task_id
        return await self.llm_factory.chat(messages, **kwargs)

    async def create_plan(self, task: str, intent: str) -> List[Dict[str, Any]]:
        """
        创建执行计划

        Args:
            task: 用户任务描述
            intent: 检测到的意图

        Returns:
            执行计划列表
        """
        logger.info(f"[Planner] 为任务创建计划: {task[:80]}... | 意图: {intent}")

        # 1. 尝试 LLM 动态规划
        if self._use_llm:
            try:
                plan = await self._create_plan_with_llm(task, intent)
                if plan:
                    logger.info(f"[Planner] LLM 生成计划，包含 {len(plan)} 个步骤")
                    return plan
            except Exception as e:
                logger.warning(f"[Planner] LLM 规划失败: {e}")

        # 2. 降级到基于意图的启发式规划
        plan = self._create_heuristic_plan(task, intent)
        logger.info(f"[Planner] 使用启发式规划，包含 {len(plan)} 个步骤")
        return plan

    async def create_quick_todos(self, task: str) -> List[Dict[str, Any]]:
        """
        快速生成简洁的待办列表

        用于规划阶段快速输出，每行 checkbox 格式。

        Args:
            task: 用户任务描述

        Returns:
            待办列表，每项包含 id, title, action (可选), params (可选)
        """
        logger.info(f"[Planner] 快速生成待办: {task[:80]}...")

        prompt = QUICK_TODOS_PROMPT.format(task=task)

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="fast",  # 使用快速策略
                temperature=0.3,
                max_tokens=500,  # 限制 token，快速返回
            )

            content = response.content.strip()
            todos = self._parse_quick_todos(content)

            if todos:
                logger.info(f"[Planner] 生成 {len(todos)} 个待办事项")
                return todos

        except Exception as e:
            logger.warning(f"[Planner] 快速待办生成失败: {e}")

        # 降级：返回简单待办
        return self._create_fallback_todos(task)

    def _parse_quick_todos(self, content: str) -> List[Dict[str, Any]]:
        """解析快速待办输出"""
        todos = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            line = line.strip()
            # 匹配 - [ ] 或 - [x] 格式
            match = re.match(r'^[-*]\s*\[\s*[xX]?\s*\]\s*(.+)', line)
            if match:
                title = match.group(1).strip()
                if title:
                    todos.append({
                        "id": len(todos) + 1,
                        "title": title,
                        "action": None,
                        "params": {},
                        "status": "pending"
                    })

        return todos

    def _create_fallback_todos(self, task: str) -> List[Dict[str, Any]]:
        """创建降级待办"""
        return [{
            "id": 1,
            "title": f"执行任务: {task[:50]}",
            "action": "general_response",
            "params": {"message": task},
            "status": "pending"
        }]

    async def think(self, task: str, todo: Dict[str, Any], context: str = "") -> str:
        """
        Thought 阶段：分析当前状态

        Args:
            task: 用户任务
            todo: 当前待办项
            context: 历史上下文

        Returns:
            思考结果
        """
        prompt = THOUGHT_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            context=context or "（无历史记录）"
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.5,
                max_tokens=800,
            )
            return response.content.strip()
        except asyncio.CancelledError:
            logger.warning(f"[Planner] think LLM 调用被取消")
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Thought 阶段失败: {e}")
            return f"思考中...（LLM 调用失败: {e}）"

    async def plan_action(
        self,
        task: str,
        todo: Dict[str, Any],
        thought: str
    ) -> Dict[str, Any]:
        """
        Planning 阶段：生成执行动作

        Args:
            task: 用户任务
            todo: 当前待办项
            thought: 思考结果

        Returns:
            动作配置 {action, params, reason}
        """
        skill_list = self._get_skill_list_str()

        prompt = PLANNING_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            thought=thought,
            skill_list=skill_list
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=500,
            )

            content = response.content.strip()
            plan_result = self._parse_planning_response(content, todo)

            # 验证并补充必要参数
            plan_result["params"] = self._ensure_required_params(
                plan_result["action"],
                plan_result["params"],
                todo
            )

            return plan_result

        except Exception as e:
            logger.warning(f"[Planner] Planning 阶段失败: {e}")
            return {
                "action": "general_response",
                "params": {"message": f"执行待办: {todo.get('title', '')}"},
                "reason": f"降级执行（LLM 调用失败: {e}）"
            }

    async def plan_action_with_feedback(
        self,
        task: str,
        todo: Dict[str, Any],
        thought: str,
        last_error: str = None,
        last_result: str = None
    ) -> Dict[str, Any]:
        """
        Planning 阶段：生成执行动作（带错误反馈）

        如果上一步执行失败，会分析错误原因并调整参数。

        Args:
            task: 用户任务
            todo: 当前待办项
            thought: 思考结果
            last_error: 上一步的错误信息
            last_result: 上一步的执行结果

        Returns:
            动作配置 {action, params, reason}
        """
        skill_list = self._get_skill_list_str()

        # 如果有错误，在 prompt 中添加错误反馈
        feedback_section = ""
        if last_error:
            feedback_section = f"""
## 上一步执行失败
错误信息: {last_error}
执行结果: {last_result}

请分析失败原因，并给出修正后的动作和参数。

**重要**: 必须修正上一步缺失的参数，特别是 `path` 参数必须明确指定值。"""

        prompt = f"""基于你的思考，制定具体的执行动作。

## 用户任务
{task}

## 当前待办
todo_id: {todo.get("id", 0)}
title: {todo.get("title", "")}

## 你的思考
{thought}
{feedback_section}

## 可用工具
{skill_list}

## 输出要求（必须遵守）
1. 动作名称必须是上面列表中的有效名称
2. **参数必须完整且具体**:
   - file_operations: 必须包含 path、operation
   - http_client: 必须包含 url
   - code_generator: 必须包含 requirements/language
3. 如果上一步失败，必须修正对应的参数

## 输出格式（严格按此格式）
```
动作: <action_name>
参数: {{"key": "value", "key2": "value2"}}
原因: <为什么选择这个动作>
```"""

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=500,
            )

            content = response.content.strip()
            plan_result = self._parse_planning_response(content, todo)

            # 验证并补充必要参数
            plan_result["params"] = self._ensure_required_params(
                plan_result["action"],
                plan_result["params"],
                todo
            )

            return plan_result

        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Planning 阶段失败: {e}")
            return {
                "action": "general_response",
                "params": {"message": f"执行待办: {todo.get('title', '')}"},
                "reason": f"降级执行（LLM 调用失败: {e}）"
            }

    def _ensure_required_params(
        self,
        action: str,
        params: Dict[str, Any],
        todo: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        确保必要参数存在，必要时从 session 查询或设置默认值

        注意：
        - 不生成带时间戳的临时 project_name，避免与 file_operations skill 中的
          命名规范不一致
        - task_path 由 main_graph._ensure_task_path 统一处理
        """
        params = params.copy() if params else {}

        if action == "file_operations":
            if "operation" not in params:
                params["operation"] = "write"

        elif action == "http_client":
            if "url" not in params:
                params["url"] = ""
            if "method" not in params:
                params["method"] = "GET"

        elif action == "code_generator":
            if "requirements" not in params and "language" not in params:
                params["requirements"] = todo.get("title", "生成代码")

        return params

    def _parse_planning_response(self, content: str, todo: Dict[str, Any]) -> Dict[str, Any]:
        """解析 Planning 阶段的响应"""
        result = {
            "action": todo.get("action") or "general_response",
            "params": todo.get("params", {}),
            "reason": ""
        }

        # 解析动作
        action_match = re.search(r'动作[:：]\s*(\w+)', content)
        if action_match:
            result["action"] = action_match.group(1)

        # 解析参数
        # 使用非贪心匹配，只取到第一个代码块结束或行尾，防止 JSON 后的 content 混入
        params_match = re.search(r'参数[:：]\s*(.+?)(?:\n```|\n原因:|$)', content, re.DOTALL)
        if params_match:
            params_str = params_match.group(1).strip()

            # 1. 尝试解析为 JSON（支持 {"key": "value"} 格式）
            parsed = self._extract_json(params_str)
            if parsed is not None:
                if isinstance(parsed, dict):
                    result["params"] = parsed
                else:
                    result["params"] = {"value": parsed}
            else:
                # 2. 尝试解析为 key-value 格式 (key: value 或 key=value)
                parsed_params = self._parse_key_value_params(params_str)
                if parsed_params:
                    result["params"] = parsed_params
                else:
                    # 3. 降级：保留原始字符串（仅在无法解析时）
                    result["params"] = {"raw": params_str}

        # 解析原因
        reason_match = re.search(r'原因[:：]\s*(.+)', content)
        if reason_match:
            result["reason"] = reason_match.group(1).strip()

        return result

    def _extract_json(self, text: str) -> Optional[Any]:
        """
        从文本中提取 JSON 对象/数组，支持不规范的 LLM 输出。

        处理以下常见问题：
        - JSON 后紧跟换行、原因说明等非 JSON 内容
        - JSON 末尾有多余逗号
        - JSON 包含尾随注释
        """
        if not text:
            return None

        text = text.strip()

        # 找到 JSON 开始位置
        json_start = text.find('{')
        if json_start < 0:
            json_start = text.find('[')
            if json_start < 0:
                return None

        json_candidate = text[json_start:]

        # 尝试直接解析
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass

        # 策略1：截取到第一个有效的 JSON 结束位置（处理尾部混入内容）
        depth = 0
        in_string = False
        escape_next = False
        end_pos = -1

        for i, ch in enumerate(json_candidate):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch == '{' or ch == '[':
                depth += 1
            elif ch == '}' or ch == ']':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        if end_pos > 0:
            json_str = json_candidate[:end_pos]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 策略2：移除多余逗号（如 "key": "value", } 或 "key": "value", ]）
        cleaned = re.sub(r',\s*([}\]])', r'\1', json_candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 策略3：移除尾随注释（// 或 /* ... */）
        cleaned = re.sub(r'//.*', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return None

    def _parse_key_value_params(self, params_str: str) -> Dict[str, Any]:
        """
        解析 key-value 格式的参数

        支持格式:
        - path: ./flask_blog
        - path=./flask_blog
        - url: xxx, method: GET
        """
        result = {}

        # 匹配 key: value 或 key=value 格式
        # 支持逗号分隔的多个参数
        pairs = re.split(r'[,\n]', params_str)
        for pair in pairs:
            pair = pair.strip()
            if not pair:
                continue

            # 尝试 key: value 格式
            match = re.match(r'^(\w+)\s*[:=]\s*(.+)$', pair)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip().strip('"\'')
                result[key] = value

        return result

    async def observe(
        self,
        task: str,
        todo: Dict[str, Any],
        action: str,
        params: Dict[str, Any],
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Observation 阶段：验证执行结果

        Args:
            task: 用户任务
            todo: 当前待办项
            action: 执行的动作
            params: 执行参数
            result: 执行结果

        Returns:
            观察结果 {completed, reason, suggestion, success}
        """
        prompt = OBSERVATION_PROMPT.format(
            task=task,
            todo_id=todo.get("id", 0),
            title=todo.get("title", ""),
            action=action,
            params=str(params),
            result=str(result)
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=400,
            )

            content = response.content.strip()
            return self._parse_observation_response(content)

        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] Observation 阶段失败: {e}")
            # 降级：根据成功状态判断
            return {
                "completed": result.get("success", False),
                "reason": f"观察完成（LLM 调用失败: {e}）",
                "suggestion": "继续" if result.get("success") else "调整",
                "success": result.get("success", False)
            }

    def _parse_observation_response(self, content: str) -> Dict[str, Any]:
        """解析 Observation 阶段的响应"""
        result = {
            "completed": False,
            "reason": "无法判断",
            "suggestion": "继续",
            "success": False
        }

        # 解析完成状态
        if "已完成" in content:
            result["completed"] = True
            result["success"] = True
        elif "部分完成" in content:
            result["completed"] = False
            result["success"] = True
        elif "未完成" in content:
            result["completed"] = False
            result["success"] = False

        # 解析原因
        reason_match = re.search(r'原因[:：]\s*(.+)', content)
        if reason_match:
            result["reason"] = reason_match.group(1).strip()

        # 解析建议
        suggestion_match = re.search(r'建议[:：]\s*(.+)', content)
        if suggestion_match:
            result["suggestion"] = suggestion_match.group(1).strip()

        return result

    async def analyze_plan(self, task: str, plan: List[Dict[str, Any]]) -> str:
        """
        对执行计划中的每个步骤进行深入分析

        Args:
            task: 用户任务描述
            plan: 执行计划列表

        Returns:
            每个步骤的分析描述
        """
        if not plan:
            return ""

        logger.info(f"[Planner] 分析计划，包含 {len(plan)} 个步骤")

        # 将计划转为可读格式
        plan_str = "\n".join([
            f"  步骤 {p.get('step', i+1)}: [{p.get('action')}] {p.get('description', '')}"
            for i, p in enumerate(plan)
        ])

        prompt = PLAN_ANALYSIS_PROMPT.format(
            task=task,
            plan=plan_str
        )

        try:
            response = await self._llm_chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=1500,
            )
            return response.content.strip()
        except asyncio.CancelledError:
            raise  # 传播取消信号，不吞掉
        except Exception as e:
            logger.warning(f"[Planner] 计划分析失败: {e}")
            # 降级：返回简单描述
            return self._generate_simple_analysis(plan)

    async def _create_plan_with_llm(self, task: str, intent: str) -> Optional[List[Dict[str, Any]]]:
        """使用 LLM 生成执行计划"""
        skill_list = self._get_skill_list_str()

        # 尝试检索相似经验（如果有经验库）
        similar_experiences = await self._retrieve_similar_experiences(task)
        experience_context = ""
        if similar_experiences:
            experience_context = f"\n\n## 参考经验（可借鉴）：\n{similar_experiences}"

        prompt = f"{self.PLANNING_PROMPT.format(skill_list=skill_list)}\n\n用户任务: {task}\n检测到的意图: {intent}{experience_context}"

        response = await self._llm_chat(
            messages=[{"role": "user", "content": prompt}],
            model=None,
            strategy="quality",  # 规划需要高质量
            temperature=0.3,
            max_tokens=1500,
        )

        content = response.content.strip()
        return self._parse_plan(content, task, intent)

    def _create_heuristic_plan(self, task: str, intent: str) -> List[Dict[str, Any]]:
        """基于意图的启发式规划（降级方案）"""
        base_actions = self._fallback_intents.get(intent, ["general_response"])

        plan = []
        for i, action in enumerate(base_actions):
            plan.append({
                "step": i + 1,
                "action": action,
                "params": self._generate_params_for_action(action, task),
                "description": self._get_action_description(action),
                "parallel": False,
                "depends_on": [i] if i > 0 else [],
            })

        return plan

    def _generate_params_for_action(self, action: str, task: str) -> Dict[str, Any]:
        """为 Skill 生成参数"""
        if action == "http_client":
            # 尝试从任务中提取 URL
            url_match = re.search(r'https?://[^\s]+', task)
            return {
                "url": url_match.group() if url_match else "",
                "method": "GET",
            }
        elif action == "code_generator":
            # 尝试从任务中提取语言信息
            lang_map = {
                "python": ["python", "Python", ".py"],
                "javascript": ["javascript", "js", "JavaScript", "JS"],
                "typescript": ["typescript", "ts", "TypeScript"],
                "go": ["golang", "go ", "Go "],
                "rust": ["rust", "Rust"],
            }
            for lang, keywords in lang_map.items():
                if any(k in task for k in keywords):
                    return {"language": lang, "requirements": task}
            return {"requirements": task}
        elif action == "notification":
            return {"content": task}
        elif action == "search":
            # 提取搜索关键词
            query = re.sub(r'搜索|查找|找一下', '', task)
            return {"query": query.strip(), "limit": 10}
        else:
            return {"input": task}

    def _get_action_description(self, action: str) -> str:
        """获取 Skill 描述"""
        descriptions = {
            "http_client": "发起 HTTP 请求获取数据",
            "code_generator": "生成代码",
            "data_processor": "处理和转换数据",
            "file_operations": "执行文件操作",
            "notification": "发送通知消息",
            "search": "搜索相关信息",
            "general_response": "生成通用响应",
        }
        return descriptions.get(action, "执行操作")

    async def _retrieve_similar_experiences(self, task: str) -> Optional[str]:
        """从经验库检索相似经验（预留接口）"""
        # TODO: 后续集成经验库
        # from app.agent.experience.retriever import ExperienceRetriever
        # retriever = ExperienceRetriever()
        # experiences = await retriever.retrieve(task, top_k=2)
        # ...
        return None

    def _parse_plan(self, content: str, task: str, intent: str) -> Optional[List[Dict[str, Any]]]:
        """解析 LLM 返回的计划"""
        # 尝试直接解析 JSON
        try:
            plan = json.loads(content)
            if isinstance(plan, list) and len(plan) > 0:
                return self._validate_and_normalize_plan(plan)
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON
        json_match = re.search(r'\[[\s\S]*\]', content)
        if json_match:
            try:
                plan = json.loads(json_match.group())
                if isinstance(plan, list) and len(plan) > 0:
                    return self._validate_and_normalize_plan(plan)
            except json.JSONDecodeError:
                pass

        # 解析失败，返回 None 触发降级
        logger.warning(f"[Planner] 无法解析 LLM 计划，触发降级")
        return None

    def _validate_and_normalize_plan(self, plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证并标准化计划"""
        valid_actions = set(AVAILABLE_SKILLS.keys())
        validated_plan = []

        for item in plan:
            # 验证 action 是否有效
            action = item.get("action")
            if action not in valid_actions:
                logger.warning(f"[Planner] 跳过无效 action: {action}")
                continue

            validated_plan.append({
                "step": len(validated_plan) + 1,
                "action": action,
                "params": item.get("params", {}),
                "description": item.get("description", ""),
                "parallel": bool(item.get("parallel", False)),
                "depends_on": [int(d) for d in item.get("depends_on", []) if isinstance(d, int)],
            })

        return validated_plan

    async def refine_plan(
        self,
        plan: List[Dict[str, Any]],
        feedback: str
    ) -> List[Dict[str, Any]]:
        """
        根据反馈优化计划

        Args:
            plan: 当前执行计划
            feedback: 用户反馈或错误信息

        Returns:
            优化后的计划
        """
        logger.info(f"[Planner] 根据反馈优化计划: {feedback[:100]}...")

        if self._use_llm:
            try:
                # 将计划转为字符串
                plan_str = json.dumps(plan, ensure_ascii=False, indent=2)

                prompt = self.REFINE_PROMPT.format(
                    current_plan=plan_str,
                    feedback=feedback
                )

                response = await self._llm_chat(
                    messages=[{"role": "user", "content": prompt}],
                    model=None,
                    strategy="quality",
                    temperature=0.3,
                    max_tokens=1500,
                )

                optimized = self._parse_plan(response.content, "", "")
                if optimized:
                    logger.info(f"[Planner] LLM 优化计划完成，包含 {len(optimized)} 个步骤")
                    return optimized
            except Exception as e:
                logger.warning(f"[Planner] LLM 优化失败: {e}")

        # 降级：简单调整计划
        return self._simple_plan_adjustment(plan, feedback)

    def _simple_plan_adjustment(
        self,
        plan: List[Dict[str, Any]],
        feedback: str
    ) -> List[Dict[str, Any]]:
        """简单的计划调整（降级方案）"""
        feedback_lower = feedback.lower()

        # 如果是超时错误，增加超时参数
        if "timeout" in feedback_lower or "超时" in feedback_lower:
            for step in plan:
                if step.get("action") == "http_client":
                    step["params"]["timeout"] = 60

        # 如果是参数错误，简化参数
        if "参数" in feedback_lower or "param" in feedback_lower:
            for step in plan:
                step["params"] = {}

        return plan

    def _generate_simple_analysis(self, plan: List[Dict[str, Any]]) -> str:
        """生成简单的计划分析（降级方案）"""
        analyses = []
        for i, step in enumerate(plan):
            action = step.get("action", "unknown")
            desc = step.get("description", "")
            analyses.append(
                f"**步骤 {i+1}: [{action}]**\n"
                f"- 目的：{desc or '执行指定操作'}\n"
                f"- 策略：调用 {action} 完成此步骤\n"
                f"- 注意：确保参数正确传递"
            )
        return "\n\n".join(analyses)

    def get_available_skills(self) -> Dict[str, Dict[str, Any]]:
        """获取所有可用 Skill"""
        try:
            loader = get_loader()
            schemas = loader.get_schemas()
            return {s["name"]: s for s in schemas}
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill 列表失败: {e}，使用备用方案")
            return AVAILABLE_SKILLS.copy()

    def get_skill_info(self, action: str) -> Optional[Dict[str, Any]]:
        """获取指定 Skill 的信息"""
        try:
            loader = get_loader()
            metadata = loader.get_metadata(action)
            if metadata:
                return metadata.to_dict()
        except Exception as e:
            logger.warning(f"[Planner] 获取 Skill {action} 信息失败: {e}")
        return AVAILABLE_SKILLS.get(action)
