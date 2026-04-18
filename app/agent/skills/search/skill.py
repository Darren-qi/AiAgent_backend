"""Search Skill - 信息搜索技能"""

import json
import re
import logging
from typing import Dict, Any

from app.agent.skills.core.base_skill import BaseSkill, SkillResult
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class SearchSkill(BaseSkill):
    """信息搜索 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "query", "type": "string", "required": True, "description": "搜索关键词"},
        {"name": "engine", "type": "string", "required": False, "description": "搜索引擎", "default": "default"},
        {"name": "limit", "type": "number", "required": False, "description": "返回结果数量", "default": 5},
    ]

    def __init__(self):
        super().__init__()
        self.name = "search"
        self.description = "信息搜索与检索"
        self.parameters = self.DEFAULT_PARAMETERS

    async def execute(self, **kwargs) -> SkillResult:
        query = kwargs.get("query", "")
        engine = kwargs.get("engine", "default")
        limit = kwargs.get("limit", 5)

        if not query:
            return SkillResult(success=False, error="缺少 query 参数")

        try:
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
        try:
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

            content = response.content.strip()
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                results = json.loads(json_match.group())
                return results[:limit]

            return [{"title": query, "description": content[:500], "score": 0.8}]

        except Exception as e:
            logger.warning(f"[Search] LLM 后备搜索失败: {e}")
            return [{"title": query, "description": "搜索服务暂时不可用", "score": 0}]


# 导出执行入口
skill = SearchSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
