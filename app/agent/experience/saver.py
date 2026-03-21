"""经验存储器"""

import logging
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from app.agent.experience.base import Experience, BaseExperienceStore

logger = logging.getLogger(__name__)


class ExperienceSaver:
    """
    经验存储器

    负责将成功执行的经验保存到经验库中。
    支持自动分析和提取经验元信息。
    """

    def __init__(self, store: Optional[BaseExperienceStore] = None):
        self._store = store
        self._pending_queue: List[Dict[str, Any]] = []

    async def save(
        self,
        task: str,
        task_type: str,
        plan: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
        success: bool,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        保存执行经验

        Args:
            task: 原始任务描述
            task_type: 任务类型（crawler/code/search等）
            plan: 执行计划
            results: 执行结果
            success: 是否成功
            metadata: 附加元数据

        Returns:
            经验ID
        """
        logger.info(f"[ExperienceSaver] 保存经验: 任务类型={task_type}, 成功={success}")

        if not success:
            logger.info("[ExperienceSaver] 跳过失败经验")
            return None

        try:
            # 构建经验描述
            description = self._generate_description(task, plan, results)

            # 提取解决方案
            solution = self._extract_solution(results)

            # 构建经验对象
            experience = Experience(
                id=self._generate_id(task, task_type),
                task=task,
                task_type=task_type,
                description=description,
                solution=solution,
                steps=plan,
                success=success,
                created_at=datetime.now(),
                success_count=1,
                metadata=metadata or {}
            )

            # 保存到存储
            if self._store:
                exp_id = await self._store.save(experience)
                logger.info(f"[ExperienceSaver] 经验已保存: {exp_id}")
                return exp_id
            else:
                # 使用内存存储
                self._pending_queue.append(self._experience_to_dict(experience))
                logger.info("[ExperienceSaver] 经验已保存到内存队列")
                return experience.id

        except Exception as e:
            logger.error(f"[ExperienceSaver] 保存经验失败: {e}")
            return None

    def _generate_description(
        self,
        task: str,
        plan: List[Dict],
        results: List[Dict]
    ) -> str:
        """生成经验描述"""
        action_count = len(plan)
        success_count = sum(1 for r in results if r.get("success", False))

        steps_summary = []
        for p in plan[:5]:  # 最多5步
            action = p.get("action", "unknown")
            desc = p.get("description", "")
            steps_summary.append(f"{action}({desc[:30]})" if desc else action)

        return f"任务: {task[:200]}\n" \
               f"执行步骤: {' -> '.join(steps_summary)}\n" \
               f"成功率: {success_count}/{action_count}"

    def _extract_solution(self, results: List[Dict]) -> str:
        """从结果中提取解决方案摘要"""
        solutions = []

        for r in results:
            if r.get("success"):
                data = r.get("data", {})
                if isinstance(data, dict):
                    # 提取关键信息
                    if "response" in data:
                        solutions.append(str(data["response"])[:300])
                    elif "code" in data:
                        solutions.append(f"代码生成: {data.get('language', 'unknown')}")
                    elif "results" in data:
                        solutions.append(f"结果数量: {len(data.get('results', []))}")

        return "\n\n".join(solutions[:3]) if solutions else "执行成功"

    def _generate_id(self, task: str, task_type: str) -> str:
        """生成唯一ID"""
        import hashlib
        content = f"{task_type}:{task[:100]}:{datetime.now().isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def _experience_to_dict(self, exp: Experience) -> Dict[str, Any]:
        """将经验对象转为字典"""
        return {
            "id": exp.id,
            "task": exp.task,
            "task_type": exp.task_type,
            "description": exp.description,
            "solution": exp.solution,
            "steps": exp.steps,
            "success": exp.success,
            "created_at": exp.created_at.isoformat(),
            "success_count": exp.success_count,
            "metadata": exp.metadata,
        }

    async def batch_save(
        self,
        experiences: List[Dict[str, Any]]
    ) -> List[Optional[str]]:
        """批量保存经验"""
        results = []
        for exp_data in experiences:
            exp_id = await self.save(**exp_data)
            results.append(exp_id)
        return results

    async def update_success_count(self, exp_id: str) -> bool:
        """更新经验的成功次数"""
        if self._store:
            try:
                await self._store.increment_success(exp_id)
                logger.info(f"[ExperienceSaver] 更新成功计数: {exp_id}")
                return True
            except Exception as e:
                logger.error(f"[ExperienceSaver] 更新成功计数失败: {e}")

        return False

    def get_pending_count(self) -> int:
        """获取待保存经验数量"""
        return len(self._pending_queue)

    def get_pending_experiences(self) -> List[Dict[str, Any]]:
        """获取待保存的经验列表"""
        return self._pending_queue.copy()

    def clear_pending(self) -> None:
        """清空待保存队列"""
        self._pending_queue.clear()


class MemoryExperienceStore(BaseExperienceStore):
    """
    内存经验存储

    用于开发和测试环境。生产环境应使用数据库或向量数据库。
    """

    def __init__(self):
        self._experiences: Dict[str, Experience] = {}

    async def save(self, experience: Experience) -> str:
        self._experiences[experience.id] = experience
        return experience.id

    async def get(self, exp_id: str) -> Optional[Experience]:
        return self._experiences.get(exp_id)

    async def search(
        self,
        query: str,
        task_type: Optional[str] = None,
        top_k: int = 5
    ) -> List[Experience]:
        results = []

        for exp in self._experiences.values():
            if task_type and exp.task_type != task_type:
                continue

            if query:
                # 简单的文本匹配
                query_lower = query.lower()
                if (query_lower in exp.task.lower() or
                    query_lower in exp.description.lower() or
                    query_lower in exp.solution.lower()):
                    results.append(exp)
            else:
                results.append(exp)

        # 按成功次数和创建时间排序
        results.sort(key=lambda x: (x.success_count, x.created_at), reverse=True)
        return results[:top_k]

    async def delete(self, exp_id: str) -> bool:
        if exp_id in self._experiences:
            del self._experiences[exp_id]
            return True
        return False

    async def increment_success(self, exp_id: str) -> None:
        exp = self._experiences.get(exp_id)
        if exp:
            exp.success_count += 1

    def get_all(self) -> List[Experience]:
        return list(self._experiences.values())

    def count(self) -> int:
        return len(self._experiences)
