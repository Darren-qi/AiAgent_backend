"""召回判定：触发词快层 → 向量阈值层 → (可选 LLM 层，默认关)。

embedding 在卸载时算好（每项一次），回忆侧只做内存余弦 + 阈值门：
零网络调用、零 LLM 调用。命中才 JIT 加载全文，未命中直接跳过检索。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .config import ContextConfig
from .items import ContextItem, ItemType, LoadState

# 向量计算器：(text) -> embedding；None 表示未接入（跳过向量层）
EmbedFn = Callable[[str], list[float] | None]


@dataclass
class RecallResult:
    """可解释召回结果。"""

    triggered_by: str = ""          # trigger / vector / llm / none
    matched_triggers: list[str] = field(default_factory=list)
    loaded_ids: list[str] = field(default_factory=list)
    skipped: bool = False           # 未命中 → 跳过检索
    best_similarity: float = 0.0
    reasons: list[str] = field(default_factory=list)


class RecallEngine:
    """按配置 mode 分层执行：off / trigger_only / trigger+vector。"""

    def __init__(self, cfg: ContextConfig,
                 embed_fn: EmbedFn | None = None,
                 llm_judge_fn: Callable[[str, list[ContextItem]], list[str]] | None = None
                 ) -> None:
        self.cfg = cfg
        self.recall_cfg = cfg.recall
        self.embed_fn = embed_fn
        self.llm_judge_fn = llm_judge_fn
        # item_id -> embedding（卸载/注册时填充，由 manager 调 store_embedding）
        self._vectors: dict[str, list[float]] = {}

    # —— 向量登记（turn 卸载 / 注册时调用，回忆侧不再算） ——

    def store_embedding(self, item_id: str, embedding: list[float]) -> None:
        self._vectors[item_id] = embedding

    def has_embedding(self, item_id: str) -> bool:
        """该项是否已算过向量（卸载补算的幂等判断）。"""
        return item_id in self._vectors

    def _similarity(self, query_vec: list[float], item_id: str) -> float:
        from .scoring import cosine
        vec = self._vectors.get(item_id)
        if vec is None:
            return 0.0
        return cosine(query_vec, vec)

    # —— 分层召回 ——

    def recall(self, query: str, items: dict[str, ContextItem],
               current_step: int = 0) -> RecallResult:
        rc = self.recall_cfg
        result = RecallResult()
        if not rc.enabled or rc.mode == "off":
            result.skipped = True
            result.reasons.append("recall disabled / mode=off")
            return result

        # —— 第 1 层：触发词（快、粗；按用户铁律只是快速路径）——
        hits: list[str] = []
        for word, ids in (self.cfg.trigger_map or {}).items():
            if word and word in (query or ""):
                result.matched_triggers.append(word)
                for iid in ids:
                    if iid in items:
                        hits.append(iid)
        if hits:
            result.triggered_by = "trigger"
            for iid in hits:
                it = items[iid]
                if it.state != LoadState.LOADED:
                    it.state = LoadState.LOADED   # JIT 加载全文
                it.touch(current_step)
                result.loaded_ids.append(iid)
            result.reasons.append(
                f"触发词命中 {result.matched_triggers} → 直接加载 {len(hits)} 项")
            # 触发词命中后仍可继续走向量层补漏？规范：命中触发词即加载，
            # 不再走向量（省一次计算）。返回。
            return result

        if rc.mode == "trigger_only":
            result.skipped = True
            result.reasons.append("trigger 未命中且 mode=trigger_only → 跳过检索")
            return result

        # —— 第 2 层：向量阈值（准、可跳过）——
        if self.embed_fn is None:
            result.skipped = True
            result.reasons.append("embed_fn 未接入 → 跳过向量层")
            return result
        # 先筛可比对的索引态项：没有候选就直接跳过，避免每 step 白打一次
        # embedding HTTP（query 向量只在真有东西可召回时才需要）
        cands = [iid for iid, it in items.items()
                 if it.state != LoadState.LOADED
                 and it.type not in (ItemType.SYSTEM_PROMPT, ItemType.CONSTRAINT)
                 and iid in self._vectors]
        if not cands:
            result.skipped = True
            result.reasons.append("无可比对向量 → 跳过检索")
            return result
        try:
            qvec = self.embed_fn(query)
        except Exception as e:  # noqa: BLE001 - 召回失败不阻塞主流程
            result.skipped = True
            result.reasons.append(f"embedding 失败({e}) → 跳过检索")
            return result
        if not qvec:
            result.skipped = True
            result.reasons.append("query embedding 为空 → 跳过检索")
            return result

        # 只与"索引态"的可召回项比对（已加载的不需要召回）
        scored = [(self._similarity(qvec, iid), iid) for iid in cands]

        scored.sort(reverse=True)
        best_sim, _ = scored[0]
        result.best_similarity = best_sim
        if best_sim < rc.similarity_threshold:
            result.skipped = True
            result.reasons.append(
                f"最高相似度 {best_sim:.3f} < 阈值 {rc.similarity_threshold} → 跳过加载")
            return result

        result.triggered_by = "vector"
        for sim, iid in scored[:rc.top_k]:
            if sim < rc.similarity_threshold:
                break
            it = items[iid]
            it.state = LoadState.LOADED   # JIT 加载全文
            it.touch(current_step)
            result.loaded_ids.append(iid)
            result.reasons.append(f"向量命中 {iid} sim={sim:.3f}")
        return result
