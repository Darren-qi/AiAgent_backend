"""step 级轻量卸载：Observation Masking + 索引化（禁 LLM 摘要/全量压缩）。

时机铁律：本模块的所有决策只允许在 step 之间（Observation 后钩子）执行。
全量淘汰与压缩在 manager.on_turn_end，绝不在这里。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import ContextConfig
from .items import ContextItem, ItemType, LoadState
from .scoring import Scorer

# 处理类型常量（可解释性返回用）
ACT_MASK = "masking"
ACT_OFFLOAD = "offload"
ACT_EVICT = "evict"
ACT_COMPRESS = "compress"


@dataclass
class Decision:
    """单条处理决策：项 + 类型 + 原因 + 评分（规范 §六可解释性）。"""

    item_id: str
    action: str            # masking / offload / evict / compress
    reason: str
    score: dict | None = None

    def __str__(self) -> str:
        s = f" score={self.score}" if self.score else ""
        return f"[{self.action}] {self.item_id}: {self.reason}{s}"


@dataclass
class MaskResult:
    decisions: list[Decision] = field(default_factory=list)
    tokens_freed: int = 0

    @property
    def masked_ids(self) -> list[str]:
        return [d.item_id for d in self.decisions if d.action == ACT_MASK]


def _obs_meta(item: ContextItem) -> str:
    return (f"tool={item.metadata.get('tool', '?')} "
            f"step={item.created_step}")


class StepLevelUnloader:
    """A 级（step 级）卸载：只 masking + 索引化。

    保护规则（全部硬约束）：
    1. 固定保护类型/ pinned 永不动；
    2. 最近 N step 窗口（含当前 step：created >= current - N）内的 Thought/Observation 不动；
    3. 当前 step 刚产生、尚未被 Thought 消费的 Observation 绝对不动
       （pending_observation_ids 由 manager 传入）；
    4. 被未完成 Action 依赖的 Observation 不动（依赖未完成 todo）。
    """

    def __init__(self, cfg: ContextConfig, scorer: Scorer, store=None) -> None:
        self.cfg = cfg
        self.scorer = scorer
        self.store = store   # 外部存储：masking/淘汰前保存原文，保证可恢复

    def _protected(self, item: ContextItem, current_step: int,
                   pending_obs: set, unfinished_actions: set) -> str | None:
        """返回保护原因；None=可处理。"""
        if item.is_protected:
            return "固定保护（系统提示/约束/原始请求/当前任务或 pinned）"
        if item.type in (ItemType.THOUGHT, ItemType.OBSERVATION):
            if current_step - item.created_step <= self.cfg.protect_recent_steps:
                return (f"最近 {self.cfg.protect_recent_steps} step 保护 "
                        f"(created={item.created_step}, now={current_step})")
        if item.id in pending_obs and item.created_step == current_step:
            return "当前 step 刚产生、尚未被 Thought 消费"
        if item.type == ItemType.OBSERVATION:
            # 依赖检查：observation 被未完成 Action 依赖
            dep_steps = set(item.depends_on_steps)
            if dep_steps & unfinished_actions:
                return f"被未完成 Action 依赖 (steps={sorted(dep_steps & unfinished_actions)})"
        if item.state == LoadState.INDEX_ONLY and not item.masked:
            return "已是索引态，无可卸载内容"
        return None

    def run(self, items: dict[str, ContextItem], current_step: int,
            used_tokens: int, target_tokens: int,
            pending_obs: set | None = None,
            unfinished_actions: set | None = None,
            query: str = "", topic_switched: bool = False) -> MaskResult:
        """预算超限时先 masking。仅当 masking 释放不足，才评分淘汰。

        结构化优先：优先 masking 已持久化且依赖已完成的旧 Observation；
        其次可卸载的 Observation / 旧 Thought；最后其他中段内容。
        """
        pending_obs = pending_obs or set()
        unfinished_actions = unfinished_actions or set()
        result = MaskResult()
        if not self.cfg.enable_observation_masking:
            return result

        # 候选：已加载、非保护、按结构化优先排序
        candidates: list[ContextItem] = []
        for it in items.values():
            if it.state != LoadState.LOADED or it.masked:
                continue
            if self._protected(it, current_step, pending_obs, unfinished_actions):
                continue
            candidates.append(it)

        def priority(it: ContextItem) -> tuple:
            # 0=持久化+依赖完成的旧 Obs, 1=其他 Obs/旧 Thought, 2=其他中段
            if it.type == ItemType.OBSERVATION and it.persisted:
                return (0, it.created_step)
            if it.type in (ItemType.OBSERVATION, ItemType.THOUGHT):
                return (1, it.created_step)
            return (2, it.created_step)

        candidates.sort(key=priority)

        def _preserve(it: ContextItem) -> None:
            """替换/清空前把原文存外部挂引用（被移除内容必须可恢复）。"""
            if self.store is None or it.external_ref:
                return
            if not it.content:
                return
            ref = self.store.put(it.content,
                                 {"id": it.id, "tool": it.metadata.get("tool", "")})
            it.external_ref = ref
            it.recoverable = True

        # —— 第一步：masking（主力规则）——
        for it in candidates:
            if used_tokens <= target_tokens:
                break
            tool = it.metadata.get("tool", "")
            if tool and tool in self.cfg.critical_tools:
                # 关键工具白名单：只摘要（保留一行摘要的“软占位”），不做占位符替换。
                # 摘要=确定性一行总结，非 LLM（step 级禁 LLM 摘要）。
                if "one_line" not in it.metadata:
                    continue  # 没有可保留的摘要就不动它
                freed = it.token_count - max(40, len(it.metadata["one_line"]) // 3)
                _preserve(it)
                it.masked = True
                it.mask_reason = "critical_tool_summary"
                it.content = (f"[关键工具结果摘要 tool={tool}] "
                              + it.metadata["one_line"])
                it.token_count = max(40, len(it.content) // 3)
                used_tokens -= max(0, freed)
                result.tokens_freed += max(0, freed)
                result.decisions.append(Decision(
                    it.id, ACT_MASK,
                    f"关键工具白名单 {tool}：只摘要不占位符替换",
                    self._score_dict(it, current_step, query, topic_switched)))
                continue

            # 普通项 → 占位符
            before = it.effective_tokens()
            _preserve(it)
            it.masked = True
            it.mask_reason = "budget_pressure"
            it.content = it.placeholder_text()
            it.state = LoadState.LOADED  # 占位符仍在上下文，但只剩 token 数
            freed = before - it.effective_tokens()
            used_tokens -= freed
            result.tokens_freed += freed
            result.decisions.append(Decision(
                it.id, ACT_MASK,
                f"预算压力 masking（{_obs_meta(it)}）",
                self._score_dict(it, current_step, query, topic_switched)))

        # —— 第二步：masking 不足以回到预算内 → 多信号评分淘汰（offload）——
        if used_tokens > target_tokens:
            remaining = [it for it in candidates if not it.masked]
            ranked = self.scorer.rank_asc(
                remaining, current_step, query, topic_switched,
                max_tokens=self.cfg.max_tokens)
            for sb in ranked:
                if used_tokens <= target_tokens:
                    break
                it = items[sb.item_id]
                before = it.effective_tokens()
                _preserve(it)
                # offload = 索引化 + 内容外置（原文已由 _preserve 存外部）
                it.state = LoadState.INDEX_ONLY
                it.masked = False
                it.content = ""
                freed = before
                used_tokens -= freed
                result.tokens_freed += freed
                result.decisions.append(Decision(
                    it.id, ACT_OFFLOAD,
                    f"评分淘汰（masking 不足）：{_obs_meta(it)}",
                    {"total": round(sb.total, 3), "similarity": round(sb.similarity, 3),
                     "recency": round(sb.recency, 3),
                     "frequency": round(sb.frequency, 3),
                     "size_penalty": round(sb.size_penalty, 3),
                     "weights": sb.weights}))
        return result

    def _score_dict(self, item: ContextItem, current_step: int,
                    query: str, topic_switched: bool) -> dict:
        sb = self.scorer.score(item, current_step, query, topic_switched,
                               max_tokens=self.cfg.max_tokens)
        return {"total": round(sb.total, 3), "similarity": round(sb.similarity, 3),
                "recency": round(sb.recency, 3), "frequency": round(sb.frequency, 3),
                "size_penalty": round(sb.size_penalty, 3), "weights": sb.weights}
