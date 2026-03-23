"""规划器节点 - LLM 动态规划"""

import json
import re
import logging
from typing import Dict, Any, List, Optional

from app.agent.llm.factory import LLMFactory
from app.agent.skills.registry import registry

logger = logging.getLogger(__name__)

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


# Skill 清单（用于规划参考）
AVAILABLE_SKILLS = {
    "http_client": {
        "description": "发起 HTTP/HTTPS 请求，获取网页内容或 API 数据",
        "params": ["url", "method", "headers", "timeout"],
        "use_for": ["爬取网页", "调用API", "获取数据"]
    },
    "code_generator": {
        "description": "生成代码，支持多种编程语言",
        "params": ["language", "requirements", "framework"],
        "use_for": ["写代码", "生成代码", "编程"]
    },
    "data_processor": {
        "description": "数据处理、转换、统计分析",
        "params": ["operation", "input_data", "options"],
        "use_for": ["数据处理", "统计分析", "数据转换"]
    },
    "file_operations": {
        "description": "文件读写、目录操作",
        "params": ["operation", "path", "content"],
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

    @property
    def llm_factory(self) -> LLMFactory:
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    def _get_skill_list_str(self) -> str:
        """生成 Skill 列表字符串"""
        lines = []
        for name, info in AVAILABLE_SKILLS.items():
            params = ", ".join(info["params"]) if info["params"] else "无"
            use_for = ", ".join(info["use_for"])
            lines.append(f"- **{name}**: {info['description']} | 参数: {params} | 适用: {use_for}")
        return "\n".join(lines)

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
            response = await self.llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                model=None,
                strategy="quality",
                temperature=0.3,
                max_tokens=1500,
            )
            return response.content.strip()
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

        response = await self.llm_factory.chat(
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

                response = await self.llm_factory.chat(
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
        return AVAILABLE_SKILLS.copy()

    def get_skill_info(self, action: str) -> Optional[Dict[str, Any]]:
        """获取指定 Skill 的信息"""
        return AVAILABLE_SKILLS.get(action)
