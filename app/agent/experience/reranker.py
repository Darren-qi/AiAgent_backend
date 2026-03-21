"""
经验重排序模块
"""

from typing import List, Dict, Any
from app.agent.experience.base import Experience


class ExperienceReranker:
    """
    经验重排序器

    对检索到的经验进行重排序，提高相关性。
    """

    def __init__(self):
        pass

    async def rerank(
        self,
        experiences: List[Experience],
        query: str,
        context: Dict[str, Any]
    ) -> List[Experience]:
        """
        重排序经验列表

        综合考虑：
        - 原始相关性分数
        - 成功次数（越多越靠前）
        - 时间衰减（越新的越靠前）
        - 类型匹配度
        """
        if not experiences:
            return experiences

        scored = []
        for exp in experiences:
            score = self._calculate_score(exp, query, context)
            scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored]

    def _calculate_score(
        self,
        exp: Experience,
        query: str,
        context: Dict[str, Any]
    ) -> float:
        """计算综合分数"""
        base_score = 0.5

        success_boost = min(exp.success_count * 0.1, 0.5)

        recency_boost = self._get_recency_boost(exp)

        type_match_boost = 0.0
        if context.get("task_type") == exp.task_type:
            type_match_boost = 0.2

        total_score = base_score + success_boost + recency_boost + type_match_boost
        return min(total_score, 1.0)

    def _get_recency_boost(self, exp: Experience) -> float:
        """计算时间衰减boost"""
        days_old = (datetime.now() - exp.created_at).days

        if days_old <= 7:
            return 0.2
        elif days_old <= 30:
            return 0.1
        elif days_old <= 90:
            return 0.0
        else:
            return -0.1

    def filter_by_threshold(
        self,
        experiences: List[Experience],
        threshold: float = 0.3
    ) -> List[Experience]:
        """过滤低分经验"""
        return [exp for exp in experiences if exp.success_count >= threshold]
