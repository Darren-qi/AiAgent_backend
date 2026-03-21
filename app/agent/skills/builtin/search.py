"""内置 Skill - 搜索"""

import logging
from typing import Dict, Any

from app.agent.skills.base import BaseSkill, SkillResult
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class SearchSkill(BaseSkill):
    """信息搜索 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "search"
        self.description = "信息搜索与检索"
        self.parameters = [
            {"name": "query", "type": "string", "required": True, "description": "搜索关键词"},
            {"name": "engine", "type": "string", "required": False, "description": "搜索引擎: default/google/baidu"},
            {"name": "limit", "type": "number", "required": False, "description": "返回结果数量限制"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        query = kwargs.get("query", "")
        engine = kwargs.get("engine", "default")
        limit = kwargs.get("limit", 5)

        if not query:
            return SkillResult(success=False, error="缺少 query 参数")

        try:
            # 尝试使用搜索 API，如果没有则使用 LLM 知识库回答
            results = await self._search(query, engine, limit)

            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "results": results,
                    "engine": engine,
                },
                metadata={"result_count": len(results)}
            )
        except Exception as e:
            logger.error(f"[Search] 搜索失败: {e}")
            return SkillResult(success=False, error=str(e))

    async def _search(self, query: str, engine: str, limit: int) -> list:
        """执行搜索（当前使用 LLM 作为后备）"""
        # 预留搜索 API 集成接口
        # TODO: 集成真实搜索 API (Google, Baidu, SerpAPI 等)

        try:
            # 使用 LLM 生成搜索结果摘要作为后备
            llm_factory = LLMFactory.get_instance()
            prompt = f"""请根据你的知识库，搜索/提供关于"{query}"的相关信息。
请返回 {limit} 条相关信息，每条包含：
1. 标题
2. 简要描述
3. 相关度评分(0-1)

格式要求：返回 JSON 数组"""
            response = await llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy="cost",
                temperature=0.3,
                max_tokens=1000,
            )

            # 尝试解析返回结果
            import json
            import re
            content = response.content.strip()
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                results = json.loads(json_match.group())
                return results[:limit]

            # 如果解析失败，返回文本结果
            return [{"title": query, "description": content[:500], "score": 0.8}]

        except Exception as e:
            logger.warning(f"[Search] LLM 后备搜索失败: {e}")
            return [{"title": query, "description": "搜索服务暂时不可用", "score": 0}]
