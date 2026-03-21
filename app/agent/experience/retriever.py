"""经验检索器"""

import logging
import json
from typing import Dict, Any, List, Optional

from app.agent.experience.base import Experience, BaseExperienceStore
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class ExperienceRetriever:
    """
    经验检索器

    从经验库中检索与当前任务相似的历史经验。
    支持多种检索策略：向量检索、关键词检索、混合检索。
    """

    def __init__(self, store: Optional[BaseExperienceStore] = None):
        self._store = store
        self._llm_factory: Optional[LLMFactory] = None

    @property
    def llm_factory(self) -> LLMFactory:
        if self._llm_factory is None:
            self._llm_factory = LLMFactory.get_instance()
        return self._llm_factory

    async def retrieve(
        self,
        task: str,
        task_type: Optional[str] = None,
        top_k: int = 3,
        strategy: str = "hybrid"
    ) -> List[Dict[str, Any]]:
        """
        检索相似经验

        Args:
            task: 当前任务描述
            task_type: 任务类型（可选）
            top_k: 返回数量
            strategy: 检索策略 - vector/keyword/hybrid/all

        Returns:
            相似经验列表
        """
        logger.info(f"[ExperienceRetriever] 检索经验: {task[:80]}..., 策略: {strategy}")

        if strategy == "all":
            # 返回所有策略的结果
            vector_results = await self._vector_search(task, task_type, top_k)
            keyword_results = await self._keyword_search(task, task_type, top_k)
            return self._merge_results(vector_results, keyword_results, top_k)
        elif strategy == "vector":
            return await self._vector_search(task, task_type, top_k)
        elif strategy == "keyword":
            return await self._keyword_search(task, task_type, top_k)
        else:  # hybrid
            vector_results = await self._vector_search(task, task_type, top_k)
            keyword_results = await self._keyword_search(task, task_type, top_k)
            return self._merge_results(vector_results, keyword_results, top_k)

    async def _vector_search(
        self,
        task: str,
        task_type: Optional[str],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        向量相似度检索

        注意：当前实现使用 LLM 生成伪嵌入进行匹配。
        实际生产环境应集成专门的向量数据库（Milvus、Weaviate 等）。
        """
        try:
            # 方案1: 使用 LLM 生成任务特征进行匹配
            task_features = await self._extract_task_features(task)

            # 方案2: 使用 LLM 评估相似度
            if self._store:
                all_experiences = await self._get_all_experiences(task_type)
                scored = []

                for exp in all_experiences[:50]:  # 限制数量
                    similarity = await self._calculate_similarity(
                        task_features,
                        exp.description
                    )
                    if similarity > 0.5:
                        scored.append((similarity, exp))

                scored.sort(key=lambda x: x[0], reverse=True)
                return [
                    self._format_experience(exp, score)
                    for score, exp in scored[:top_k]
                ]

        except Exception as e:
            logger.warning(f"[ExperienceRetriever] 向量检索失败: {e}")

        return []

    async def _keyword_search(
        self,
        task: str,
        task_type: Optional[str],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """关键词检索（基于 BM25 的简化实现）"""
        try:
            if self._store:
                all_experiences = await self._get_all_experiences(task_type)
                scored = []

                task_words = set(task.lower().split())
                for exp in all_experiences:
                    # 计算词重叠
                    exp_words = set((exp.description + " " + exp.task).lower().split())
                    overlap = len(task_words & exp_words)
                    if overlap > 0:
                        score = overlap / max(len(task_words), len(exp_words))
                        scored.append((score, exp))

                scored.sort(key=lambda x: x[0], reverse=True)
                return [
                    self._format_experience(exp, score)
                    for score, exp in scored[:top_k]
                ]

        except Exception as e:
            logger.warning(f"[ExperienceRetriever] 关键词检索失败: {e}")

        return []

    def _merge_results(
        self,
        vector_results: List[Dict],
        keyword_results: List[Dict],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """RRF 混合排序（Reciprocal Rank Fusion）"""
        scores: Dict[str, tuple] = {}

        # 向量检索得分 (RRF k=60)
        for i, result in enumerate(vector_results):
            exp_id = result.get("id", f"vec_{i}")
            rrf_score = 1 / (60 + i + 1)
            scores[exp_id] = (scores.get(exp_id, (0,))[0] + rrf_score * 0.6, result)

        # 关键词检索得分
        for i, result in enumerate(keyword_results):
            exp_id = result.get("id", f"kw_{i}")
            rrf_score = 1 / (60 + i + 1)
            if exp_id in scores:
                scores[exp_id] = (scores[exp_id][0] + rrf_score * 0.4, scores[exp_id][1])
            else:
                scores[exp_id] = (rrf_score * 0.4, result)

        # 排序并返回
        sorted_results = sorted(scores.values(), key=lambda x: x[0], reverse=True)
        return [result for _, result in sorted_results[:top_k]]

    async def _extract_task_features(self, task: str) -> str:
        """使用 LLM 提取任务特征"""
        prompt = f"""分析以下任务，提取关键特征（动词+名词+限定词）：

任务: {task}

请用简短的几句话描述任务的核心特征，格式：主要是关于XXX的YYY任务，需要用到ZZZ。"""

        try:
            response = await self.llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy="cost",
                temperature=0.3,
                max_tokens=200,
            )
            return response.content
        except Exception:
            return task

    async def _calculate_similarity(self, features1: str, features2: str) -> float:
        """使用 LLM 评估两个描述的相似度"""
        prompt = f"""评估以下两个描述的相似度（0-1之间）：

描述1: {features1}

描述2: {features2}

只返回一个数字（0到1之间的小数），0表示完全不相似，1表示完全相似。"""

        try:
            response = await self.llm_factory.chat(
                messages=[{"role": "user", "content": prompt}],
                strategy="cost",
                temperature=0,
                max_tokens=10,
            )

            # 尝试解析数字
            import re
            match = re.search(r'0?\.\d+', response.content)
            if match:
                return float(match.group())

            # 检查关键词匹配
            common_words = set(features1.lower().split()) & set(features2.lower().split())
            return len(common_words) / max(len(set(features1.lower().split())), 1)

        except Exception:
            return 0.0

    async def _get_all_experiences(
        self,
        task_type: Optional[str]
    ) -> List[Experience]:
        """获取所有经验（支持缓存）"""
        if not self._store:
            return []

        try:
            # 使用空查询获取所有
            return await self._store.search(
                query="",
                task_type=task_type,
                top_k=100
            )
        except Exception:
            return []

    def _format_experience(
        self,
        exp: Experience,
        score: float
    ) -> Dict[str, Any]:
        """格式化经验为可读字典"""
        return {
            "id": exp.id,
            "task": exp.task,
            "task_type": exp.task_type,
            "description": exp.description,
            "solution": exp.solution[:500] if exp.solution else "",
            "steps": exp.steps,
            "success": exp.success,
            "success_count": exp.success_count,
            "similarity_score": score,
            "created_at": exp.created_at.isoformat() if exp.created_at else None,
        }

    async def get_relevant_plan(
        self,
        task: str,
        top_k: int = 2
    ) -> List[Dict[str, Any]]:
        """
        获取与任务相关的执行计划

        返回格式化的计划列表，供 Planner 参考。
        """
        experiences = await self.retrieve(task, top_k=top_k)

        plans = []
        for exp in experiences:
            if exp.get("steps"):
                plans.append({
                    "source": "experience",
                    "experience_id": exp.get("id"),
                    "similarity": exp.get("similarity_score", 0),
                    "steps": exp.get("steps", []),
                })

        return plans
