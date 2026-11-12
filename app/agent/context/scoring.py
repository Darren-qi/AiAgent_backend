"""多信号评分淘汰：相似性 0.4 / 新近性 0.3 / 访问频率 0.2 / 大小惩罚 0.1。

话题切换时提高相似性权重、降低访问频率权重（配置可调）。
相似性来自 embedding 余弦（注入式，未接入时用中性值 0.5，不阻塞主流程）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .config import ContextConfig
from .items import ContextItem

# 相似性计算器签名：(item, query) -> [-1,1]；None 表示未配置
SimilarityFn = Callable[[ContextItem, str], Optional[float]]


def cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度（numpy 可用时走 numpy，否则纯 Python）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        import numpy as np
        va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
        denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(va @ vb / denom) if denom else 0.0
    except Exception:  # noqa: BLE001 - numpy 缺失降级
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0


@dataclass
class ScoreBreakdown:
    """可解释评分：总分 + 分量。"""

    item_id: str
    total: float
    similarity: float
    recency: float
    frequency: float
    size_penalty: float
    weights: Dict[str, float]

    def explain(self) -> str:
        return (f"{self.item_id}: total={self.total:.3f} "
                f"(sim={self.similarity:.2f}×{self.weights['similarity']}, "
                f"rec={self.recency:.2f}×{self.weights['recency']}, "
                f"freq={self.frequency:.2f}×{self.weights['frequency']}, "
                f"size={self.size_penalty:.2f}×{self.weights['size']})")


class Scorer:
    """按配置权重计算保留价值，从低到高淘汰。"""

    def __init__(self, cfg: ContextConfig,
                 similarity_fn: Optional[SimilarityFn] = None) -> None:
        self.cfg = cfg
        self.similarity_fn = similarity_fn

    def _weights(self, topic_switched: bool) -> Dict[str, float]:
        if topic_switched:
            return {
                "similarity": self.cfg.topic_switch_weight_similarity,
                "recency": self.cfg.weight_recency,
                "frequency": self.cfg.topic_switch_weight_frequency,
                "size": self.cfg.weight_size_penalty,
            }
        return {
            "similarity": self.cfg.weight_similarity,
            "recency": self.cfg.weight_recency,
            "frequency": self.cfg.weight_frequency,
            "size": self.cfg.weight_size_penalty,
        }

    def score(self, item: ContextItem, current_step: int,
              query: str = "", topic_switched: bool = False,
              max_tokens: int = 1) -> ScoreBreakdown:
        w = self._weights(topic_switched)

        # 相似性：注入计算器 → 中性 0.5（未配置不偏置）
        sim = 0.5
        if self.similarity_fn is not None and query:
            v = self.similarity_fn(item, query)
            if v is not None:
                sim = max(0.0, min(1.0, v))

        # 新近性：按 step 差指数衰减（半衰期 5 步）
        age = max(0, current_step - item.last_access_step)
        recency = 0.5 ** (age / 5.0)

        # 访问频率：饱和归一（10 次到顶）
        frequency = min(1.0, item.access_count / 10.0)

        # 大小惩罚：越大越易被淘汰（对数归一到 64K）
        import math
        size_penalty = 1.0 - min(1.0, math.log1p(item.token_count)
                                 / math.log1p(max(1, max_tokens)))

        total = (w["similarity"] * sim + w["recency"] * recency
                 + w["frequency"] * frequency + w["size"] * size_penalty)
        return ScoreBreakdown(
            item_id=item.id, total=total, similarity=sim, recency=recency,
            frequency=frequency, size_penalty=size_penalty, weights=w)

    def rank_asc(self, candidates: List[ContextItem], current_step: int,
                 query: str = "", topic_switched: bool = False,
                 max_tokens: int = 1) -> List[ScoreBreakdown]:
        """保留价值从低到高（先淘汰的排前面）。"""
        items = [self.score(it, current_step, query, topic_switched, max_tokens)
                 for it in candidates]
        items.sort(key=lambda s: s.total)
        return items
