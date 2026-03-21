"""意图检测节点 - LLM 语义理解 + 关键词兜底"""

import json
import re
import logging
from typing import Dict, Any, List, Optional
import re
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


# 意图类型定义
INTENT_TYPES = {
    "crawler": {
        "keywords": ["爬取", "抓取", "爬虫", "抓取网站", "获取网页", "scrape", "crawl"],
        "description": "网页数据抓取任务"
    },
    "code": {
        "keywords": ["写代码", "生成代码", "编程", "代码", "开发", "写程序", "code", "python", "javascript"],
        "description": "代码编写和生成任务"
    },
    "analysis": {
        "keywords": ["分析", "统计", "报告", "研究", "研究一下", "analyze", "analysis", "report"],
        "description": "数据分析与报告生成"
    },
    "search": {
        "keywords": ["搜索", "查询", "查找", "搜索一下", "找一下", "search", "find"],
        "description": "信息搜索与检索"
    },
    "notification": {
        "keywords": ["通知", "发送", "提醒", "提醒我", "发消息", "notify", "send", "remind"],
        "description": "通知发送任务"
    },
    "file_ops": {
        "keywords": ["文件", "下载", "上传", "读取", "写入", "file", "download", "upload"],
        "description": "文件操作任务"
    },
    "data": {
        "keywords": ["数据", "处理", "转换", "清洗", "data", "process", "transform"],
        "description": "数据处理任务"
    },
    "general": {
        "keywords": [],
        "description": "通用对话"
    }
}


# 复杂度指标关键词
COMPLEXITY_HIGH_KEYWORDS = [
    "多个", "复杂", "详细", "全面", "系统", "架构", "设计", "比较",
    "详细分析", "完整", "综合", "深入", "批量", "大量",
    "compare", "complex", "multiple", "batch", "systematic"
]

COMPLEXITY_MEDIUM_KEYWORDS = [
    "一些", "部分", "几个", "整理", "整理一下", "处理",
    "some", "several", "process", "organize"
]


class IntentDetector:
    """意图检测器 - LLM 语义理解 + 关键词匹配兜底"""

    # LLM 意图识别 Prompt
    INTENT_PROMPT = """你是一个专业的用户意图识别助手。请分析用户任务的意图类型。

## 意图类型定义：
- **crawler**: 网页数据爬取、抓取网站内容
- **code**: 代码编写、代码生成、编程任务
- **analysis**: 数据分析、统计、报告生成
- **search**: 信息搜索、查询、查找
- **notification**: 通知发送、消息提醒
- **file_ops**: 文件操作、下载、上传
- **data**: 数据处理、转换、清洗
- **general**: 通用对话、问答

## 输出要求：
请以 JSON 格式返回分析结果，包含以下字段：
- **primary_intent**: 主要意图（单一最佳匹配）
- **all_intents**: 检测到的所有可能意图列表
- **confidence**: 置信度（0.0-1.0）
- **reasoning**: 简要推理过程
- **suggested_actions**: 建议的后续操作

示例输入: "帮我爬取某网站的新闻标题"
示例输出:
{
    "primary_intent": "crawler",
    "all_intents": ["crawler", "data"],
    "confidence": 0.95,
    "reasoning": "用户明确提到'爬取'和'网站'，这是典型的爬虫任务",
    "suggested_actions": ["http_client", "process_data"]
}

请分析以下用户任务："""

    # 复杂度评估 Prompt
    COMPLEXITY_PROMPT = """你是一个任务复杂度评估专家。请评估以下任务的复杂度。

## 复杂度等级定义：
- **low**: 单一步骤、简单任务，1-2步可完成
- **medium**: 多步骤、需要规划，3-5步可完成
- **high**: 复杂任务、需要多智能体协作、5步以上或需要并行处理

## 输出要求：
请以 JSON 格式返回评估结果：
- **complexity**: low/medium/high
- **estimated_steps**: 预估执行步骤数
- **reasoning**: 评估理由
- **routing**: 路由建议
  - mode: simple(单Agent直接执行)/dynamic_subgraph(动态子图并行)/multi_agent(多智能体协作)
  - parallel: 是否支持并行执行
  - max_iterations: 最大迭代次数
- **requires**: 需要的资源/能力

示例：
{
    "complexity": "medium",
    "estimated_steps": 4,
    "reasoning": "任务包含多个子任务，可以并行处理部分步骤",
    "routing": {
        "mode": "dynamic_subgraph",
        "parallel": true,
        "max_iterations": 3
    },
    "requires": ["http_client", "data_processor"]
}

请评估以下任务："""

    def __init__(self):
        self._llm_factory: Optional[LLMFactory] = None
        self._keyword_fallback = KeywordIntentDetector()
        self._use_llm = True
        self._llm_fallback_threshold = 0.5  # LLM置信度低于此值时使用关键词

    @property
    def llm_factory(self) -> LLMFactory:
        """延迟初始化 LLM 工厂"""
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    async def detect(self, task: str) -> Dict[str, Any]:
        """
        检测用户意图

        优先使用 LLM 语义理解，失败时降级到关键词匹配
        """
        # 1. 尝试 LLM 语义识别
        if self._use_llm:
            try:
                result = await self._detect_with_llm(task)
                if result.get("confidence", 0) >= self._llm_fallback_threshold:
                    logger.info(f"[IntentDetector] LLM识别结果: {result['primary_intent']} (置信度: {result['confidence']:.2f})")
                    return result
                logger.info(f"[IntentDetector] LLM置信度过低 ({result.get('confidence', 0):.2f})，使用关键词兜底")
            except Exception as e:
                logger.warning(f"[IntentDetector] LLM识别失败: {e}，使用关键词兜底")

        # 2. 降级到关键词匹配
        return await self._keyword_fallback.detect(task)

    async def _detect_with_llm(self, task: str) -> Dict[str, Any]:
        """使用 LLM 进行意图识别"""
        response = await self.llm_factory.chat(
            messages=[
                {"role": "user", "content": f"{self.INTENT_PROMPT}\n\n用户任务: {task}"}
            ],
            model=None,  # 使用默认路由策略（优先用便宜模型）
            strategy="cost",
            temperature=0.1,
            max_tokens=500,
        )

        content = response.content.strip()

        # 尝试解析 JSON
        try:
            # 尝试直接解析
            

            match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
            if match:
                json_str = match.group(1)
                result = json.loads(json_str)
            else:
                print("意图数据解析失败，检查是否为标准JSON格式")

            return self._normalize_intent_result(result)
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return self._normalize_intent_result(result)
                except json.JSONDecodeError:
                    pass

        # 解析失败，尝试从文本推断
        return self._parse_intent_from_text(task, content)

    def _normalize_intent_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """标准化意图识别结果"""
        primary = result.get("primary_intent", "general")
        all_intents = result.get("all_intents", [primary])

        # 验证意图类型有效性
        valid_intents = list(INTENT_TYPES.keys())
        if primary not in valid_intents:
            primary = "general"

        normalized_intents = [i for i in all_intents if i in valid_intents]
        if not normalized_intents:
            normalized_intents = ["general"]

        return {
            "primary_intent": primary,
            "all_intents": normalized_intents,
            "confidence": float(result.get("confidence", 0.7)),
            "reasoning": result.get("reasoning", ""),
            "suggested_actions": result.get("suggested_actions", []),
        }

    def _parse_intent_from_text(self, task: str, text: str) -> Dict[str, Any]:
        """从文本中解析意图（当 JSON 解析失败时）"""
        text_lower = text.lower()

        # 简单的关键词匹配作为后备
        for intent, info in INTENT_TYPES.items():
            for keyword in info["keywords"]:
                if keyword in text_lower or keyword in task:
                    return {
                        "primary_intent": intent,
                        "all_intents": [intent],
                        "confidence": 0.5,
                        "reasoning": f"从LLM响应文本推断: {text[:100]}",
                        "suggested_actions": [],
                    }

        return {
            "primary_intent": "general",
            "all_intents": ["general"],
            "confidence": 0.3,
            "reasoning": f"LLM响应解析失败: {text[:100]}",
            "suggested_actions": [],
        }

    async def detect_complexity(self, task: str, intents: List[str]) -> Dict[str, Any]:
        """
        评估任务复杂度并决定路由策略

        Args:
            task: 用户任务
            intents: 检测到的意图列表

        Returns:
            包含 complexity 和 routing 的字典
        """
        # 1. 快速判断：基于关键词的启发式规则
        heuristic = self._heuristic_complexity(task, intents)
        if heuristic["use_heuristic"]:
            logger.info(f"[IntentDetector] 使用启发式复杂度评估: {heuristic['complexity']}")
            return heuristic

        # 2. LLM 详细评估
        if self._use_llm:
            try:
                result = await self._evaluate_complexity_with_llm(task, intents)
                logger.info(f"[IntentDetector] LLM复杂度评估: {result.get('complexity')}")
                return result
            except Exception as e:
                logger.warning(f"[IntentDetector] LLM复杂度评估失败: {e}")

        # 3. 降级到启发式
        return self._heuristic_complexity(task, intents)

    def _heuristic_complexity(self, task: str, intents: List[str]) -> Dict[str, Any]:
        """基于规则的启发式复杂度评估（无 LLM 调用）"""
        task_lower = task.lower()
        complexity_score = 0

        # 检查高复杂度关键词
        for keyword in COMPLEXITY_HIGH_KEYWORDS:
            if keyword in task_lower:
                complexity_score += 2

        # 检查中复杂度关键词
        for keyword in COMPLEXITY_MEDIUM_KEYWORDS:
            if keyword in task_lower:
                complexity_score += 1

        # 多意图增加复杂度
        complexity_score += len(intents) * 0.5

        # 任务长度（长任务通常更复杂）
        complexity_score += min(len(task) / 100, 3)

        # 判断复杂度等级
        if complexity_score >= 4:
            complexity = "high"
            mode = "multi_agent"
            parallel = True
            max_iterations = 10
        elif complexity_score >= 2:
            complexity = "medium"
            mode = "dynamic_subgraph"
            parallel = True
            max_iterations = 5
        else:
            complexity = "low"
            mode = "simple"
            parallel = False
            max_iterations = 3

        return {
            "complexity": complexity,
            "estimated_steps": max(1, int(complexity_score + 1)),
            "reasoning": f"启发式评估: 复杂度分数={complexity_score:.1f}",
            "routing": {
                "mode": mode,
                "parallel": parallel,
                "max_iterations": max_iterations,
            },
            "requires": intents,
            "use_heuristic": True,
        }

    async def _evaluate_complexity_with_llm(self, task: str, intents: List[str]) -> Dict[str, Any]:
        """使用 LLM 进行复杂度评估"""
        context = f"\n\n检测到的意图: {', '.join(intents)}" if intents else ""

        response = await self.llm_factory.chat(
            messages=[
                {"role": "user", "content": f"{self.COMPLEXITY_PROMPT}\n\n用户任务: {task}{context}"}
            ],
            model=None,
            strategy="cost",
            temperature=0.1,
            max_tokens=600,
        )

        content = response.content.strip()

        # 尝试解析 JSON
        try:
            result = json.loads(content)
            return self._normalize_complexity_result(result)
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                    return self._normalize_complexity_result(result)
                except json.JSONDecodeError:
                    pass

        # 解析失败，使用降级
        logger.warning(f"[IntentDetector] 复杂度JSON解析失败，使用启发式降级")
        return self._heuristic_complexity(task, intents)

    def _normalize_complexity_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """标准化复杂度评估结果"""
        complexity = result.get("complexity", "low")
        if complexity not in ["low", "medium", "high"]:
            complexity = "low"

        routing = result.get("routing", {})
        if not isinstance(routing, dict):
            routing = {"mode": "simple", "parallel": False, "max_iterations": 3}

        return {
            "complexity": complexity,
            "estimated_steps": int(result.get("estimated_steps", 1)),
            "reasoning": result.get("reasoning", ""),
            "routing": {
                "mode": routing.get("mode", "simple"),
                "parallel": routing.get("parallel", False),
                "max_iterations": int(routing.get("max_iterations", 5)),
            },
            "requires": result.get("requires", []),
            "use_heuristic": False,
        }


class KeywordIntentDetector:
    """基于关键词的意图检测器（兜底方案）"""

    async def detect(self, task: str) -> Dict[str, Any]:
        """使用关键词匹配检测意图"""
        task_lower = task.lower()

        detected = []
        for intent, info in INTENT_TYPES.items():
            for keyword in info["keywords"]:
                if keyword in task_lower:
                    if intent != "general":
                        detected.append(intent)
                    break

        if not detected:
            detected = ["general"]

        # 计算置信度
        confidence = min(len(detected) * 0.25, 0.75)
        if len(detected) >= 3:
            confidence = 0.85

        return {
            "primary_intent": detected[0],
            "all_intents": detected,
            "confidence": confidence,
            "reasoning": f"关键词匹配: {detected}",
            "suggested_actions": [],
        }
