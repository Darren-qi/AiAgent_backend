"""ContextManager：上下文加载/卸载/压缩/恢复的统一入口。

六个钩子（规范 §四/§六）：
  on_session_start  会话开始：加载系统提示/约束/原始用户请求（常驻）
  on_step_start     step 前：召回(JIT) → 按预算重新构建本 step 上下文
  on_observation    Observation 后：登记、更新预算、判定 masking（step 级）
  on_turn_end       turn 后：重量级卸载/压缩/长循环折叠（全量淘汰唯一入口）
  load / load_by_ref  按标识加载 / 按外部引用恢复
  compress          执行压缩并说明原因（budget / turn_end / manual）

铁律：step 级只 masking+索引化；LLM 摘要/全量压缩只允许在 on_turn_end。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .budget import BudgetTracker, count_tokens
from .config import ContextConfig
from .items import AttentionPosition, ContextItem, ItemType, LoadState
from .masking import ACT_COMPRESS, ACT_EVICT, ACT_MASK, ACT_OFFLOAD, \
    Decision, MaskResult, StepLevelUnloader
from .recall import RecallEngine, RecallResult
from .scoring import Scorer, SimilarityFn
from .store import ExternalStore, get_store

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """一次 step 上下文构建的结果（规范 §六：可解释）。"""

    prompt: str                      # 组装好的上下文文本
    used_tokens: int
    max_tokens: int
    omitted: List[dict] = field(default_factory=list)    # 未加载（只在索引里）
    masked: List[dict] = field(default_factory=list)     # 被 masking 的项
    decisions: List[Decision] = field(default_factory=list)
    recall: Optional[RecallResult] = None
    reasons: List[str] = field(default_factory=list)

    @property
    def usage_ratio(self) -> float:
        return self.used_tokens / self.max_tokens if self.max_tokens else 0.0


@dataclass
class CompressResult:
    reason: str                      # budget / turn_end / manual / long_loop
    before_tokens: int
    after_tokens: int
    offloaded: List[str] = field(default_factory=list)
    folded: Optional[str] = None     # 长循环折叠摘要的引用
    decisions: List[Decision] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return self.before_tokens - self.after_tokens


class ContextManager:
    """可插拔上下文管理器。embed_fn / summarizer / store 均可注入。"""

    def __init__(self, cfg: Optional[ContextConfig] = None,
                 embed_fn: Optional[Callable[[str], Optional[List[float]]]] = None,
                 similarity_fn: Optional[SimilarityFn] = None,
                 store: Optional[ExternalStore] = None,
                 summarizer: Optional[Callable[[str], str]] = None) -> None:
        self.cfg = cfg or ContextConfig()
        self.cfg.validate()
        self.store = store or get_store(self.cfg.external_store)
        self.scorer = Scorer(self.cfg, similarity_fn=similarity_fn)
        self.unloader = StepLevelUnloader(self.cfg, self.scorer, store=self.store)
        self.recall_engine = RecallEngine(self.cfg, embed_fn=embed_fn)
        self.embed_fn = embed_fn              # 卸载时补算向量用（方案 §0.2）
        self.budget = BudgetTracker(
            max_tokens=self.cfg.max_tokens,
            trigger_ratio=self.cfg.compress_trigger_ratio,
            target_ratio=self.cfg.compress_target_ratio)
        self.summarizer = summarizer          # 注入后 turn 级可用 LLM 摘要
        self.items: Dict[str, ContextItem] = {}
        self.current_step = 0
        self.turn_steps = 0                   # 本 turn 累计 step 数
        self.pending_obs: set = set()         # 当前 step 刚产生未消费的 Observation
        self.unfinished_actions: set = set()  # 未完成 Action 依赖的 step
        self.session_query = ""               # 本 turn 的任务文本（相似性基准）
        self.topic_switched = False
        self._decisions: List[Decision] = []  # 累计可解释记录

    # ─────────────────────────── 注册 / 加载 ───────────────────────────

    def register(self, item: ContextItem, load_now: bool = False) -> ContextItem:
        """注册轻量索引（默认不加载正文）。load_now=True 才进上下文。"""
        if item.id in self.items:
            return self.items[item.id]
        if not item.content:
            item.state = LoadState.INDEX_ONLY
        item.token_count = item.token_count or count_tokens(item.content)
        if load_now:
            item.state = LoadState.LOADED
            item.last_access_step = self.current_step
        self.items[item.id] = item
        return item

    def load(self, item_id: str, step: Optional[int] = None) -> Optional[str]:
        """按标识加载完整内容；返回正文或 None。"""
        it = self.items.get(item_id)
        if it is None:
            return None
        if it.state != LoadState.LOADED:
            # 索引态 → 从外部存储取回正文（JIT）
            if it.external_ref:
                content = self.store.get(it.external_ref)
                if content is None:
                    return None
                it.content = content
            it.state = LoadState.LOADED
        it.touch(step if step is not None else self.current_step)
        self._recalc_budget()
        return it.content

    def load_by_ref(self, ref: str) -> Optional[str]:
        """按外部引用恢复内容（卸载后可回查）。"""
        return self.store.get(ref)

    def load_by_trigger(self, query: str) -> RecallResult:
        """按触发词/向量加载一组内容（JIT）。"""
        r = self.recall_engine.recall(query, self.items, self.current_step)
        for iid in r.loaded_ids:
            it = self.items[iid]
            if it.state == LoadState.LOADED and not it.content and it.external_ref:
                c = self.store.get(it.external_ref)
                if c:
                    it.content = c
        self._recalc_budget()
        return r

    # ─────────── embedding 补算（方案 §0.2：卸载时算，每项一次） ───────────

    def _embed_unloaded(self) -> int:
        """为索引态缺向量的项补算 embedding。

        触发点：step 前（召回前，覆盖知识项注册）、Observation 后与 turn 后
        （覆盖两处卸载点）。embed_fn 未接入 / 向量层未启用 / 单项失败 → 跳过。
        """
        rc = self.cfg.recall
        if self.embed_fn is None or not rc.enabled or rc.mode != "trigger+vector":
            return 0
        n = 0
        for it in self.items.values():
            if it.state != LoadState.INDEX_ONLY:
                continue
            if self.recall_engine.has_embedding(it.id):
                continue
            text = it.content or (self.store.get(it.external_ref)
                                  if it.external_ref else "") or ""
            if not text:
                continue
            try:
                vec = self.embed_fn(text)
            except Exception as exc:  # noqa: BLE001 - 补算失败不阻塞主流程
                logger.warning("补算 embedding 失败(%s): %s", it.id, exc)
                continue
            if vec:
                self.recall_engine.store_embedding(it.id, vec)
                n += 1
        return n

    # ─────────────────────────── 四个钩子 ───────────────────────────

    def on_session_start(self, system_prompt: str, constraints: str = "",
                         user_request: str = "") -> BuildResult:
        """会话开始钩子：系统提示/约束/原始用户请求常驻加载。"""
        def add(iid: str, typ: ItemType, text: str,
                att: AttentionPosition) -> None:
            if not text:
                return
            self.register(ContextItem(
                id=iid, type=typ, content=text,
                token_count=count_tokens(text), attention=att,
                pinned=True, recoverable=False, persisted=True,
                state=LoadState.LOADED, created_step=0, last_access_step=0),
                load_now=True)
        add("sys", ItemType.SYSTEM_PROMPT, system_prompt, AttentionPosition.HEAD)
        add("constraint", ItemType.CONSTRAINT, constraints, AttentionPosition.HEAD)
        add("user_request", ItemType.USER_REQUEST, user_request,
            AttentionPosition.HEAD)
        self.turn_steps = 0
        self.current_step = 0
        return self.on_step_start(step=0, query=user_request, build_only=True)

    def on_step_start(self, step: int, query: str = "",
                      build_only: bool = False) -> BuildResult:
        """step 前钩子：召回(JIT) → 按预算重建本 step 上下文。

        上下文不是持续累积的历史，而是每个 step 按 token 预算重新构建。
        """
        self.current_step = step
        self.turn_steps = max(self.turn_steps, step)
        # turn 内主动卸载（先卸后召回，防刚召回又被卸；召回 load 会续租）
        self._proactive_prune(step)
        self._embed_unloaded()   # 召回前补算（知识项注册后首次可用）
        recall_res: Optional[RecallResult] = None
        if query and not build_only:
            recall_res = self.load_by_trigger(query)

        # 回收：step 边界清理已消费的 pending 观察
        self.pending_obs.clear()

        # 组装：HEAD(系统/约束/原始请求) → MIDDLE(历史/知识，按态) → TAIL(当前任务)
        head: List[str] = []
        middle: List[str] = []
        tail: List[str] = []
        omitted: List[dict] = []
        masked: List[dict] = []
        used = 0
        for it in self._sorted_items():
            if it.state == LoadState.INDEX_ONLY:
                # 未加载 → 只有索引条目，不算正文 token（不预加载）
                omitted.append({"id": it.id, "type": it.type.value,
                                "token_count": it.token_count,
                                "reason": "index_only（未命中加载条件）"})
                continue
            text = it.content
            if it.masked:
                masked.append({"id": it.id, "type": it.type.value,
                               "reason": it.mask_reason})
            seg = f"<{it.type.value} id={it.id}>\n{text}\n</{it.type.value}>"
            t = it.effective_tokens()
            # 预算硬护栏：中段超预算的非保护项不再拼入（保护项始终拼）
            if used + t > self.cfg.max_tokens and not it.is_protected \
                    and it.attention != AttentionPosition.TAIL:
                omitted.append({"id": it.id, "type": it.type.value,
                                "token_count": t,
                                "reason": "超出本 step token 预算"})
                continue
            used += t
            if it.attention == AttentionPosition.HEAD:
                head.append(seg)
            elif it.attention == AttentionPosition.TAIL:
                tail.append(seg)
            else:
                middle.append(seg)

        parts = head + middle + tail
        prompt = "\n\n".join(parts)
        reasons = []
        if recall_res:
            reasons.append(f"recall: {recall_res.triggered_by} "
                           f"loaded={recall_res.loaded_ids} "
                           f"skipped={recall_res.skipped}")
        self.budget.update(used, step=step, event="build")
        return BuildResult(
            prompt=prompt, used_tokens=used, max_tokens=self.cfg.max_tokens,
            omitted=omitted, masked=masked, recall=recall_res, reasons=reasons)

    def on_observation(self, obs_id: str, content: str, tool: str = "",
                       params_summary: str = "", one_line: str = "",
                       step: Optional[int] = None,
                       depends_on_action_step: Optional[int] = None,
                       persisted: bool = False) -> BuildResult:
        """Observation 后钩子：登记、更新预算、判定 masking（只在 step 间）。"""
        step = self.current_step if step is None else step
        # 大观察截断存档（2026-11-13 对齐 Hermes snapshot truncate-and-store）：
        # 头部进上下文、全文存外部留指针，防单次大读取撑爆本步预算
        _trunc_ref = ""
        if len(content) > self.cfg.obs_full_chars:
            _full = content
            _trunc_ref = self.store.put(
                _full, {"id": obs_id, "tool": tool, "truncated": True})
            content = _full[: self.cfg.obs_full_chars] + (
                f"\n...[内容已截断：原 {len(_full)} 字符，完整内容已存档 ref={_trunc_ref}；"
                "需要时 load_by_ref 恢复或重新 read 对应分页]")
        item = ContextItem(
            id=obs_id, type=ItemType.OBSERVATION, content=content,
            token_count=count_tokens(content),
            attention=AttentionPosition.MIDDLE, created_step=step,
            last_access_step=step, recoverable=True, persisted=persisted,
            state=LoadState.LOADED,
            external_ref=_trunc_ref or None,
            depends_on_steps=[depends_on_action_step]
            if depends_on_action_step is not None else [],
            metadata={"tool": tool, "params_summary": params_summary,
                      "one_line": one_line[:200]})
        self.register(item, load_now=True)
        self.pending_obs.add(obs_id)   # 刚产生、尚未被 Thought 消费 → 绝对保护

        self._recalc_budget()
        # 预算超限 → step 级轻量卸载（masking 优先）
        mask_res = MaskResult()
        if self.budget.over_trigger:
            mask_res = self.unloader.run(
                self.items, step, self.budget.used, self.budget.target_tokens,
                pending_obs=self.pending_obs,
                unfinished_actions=self.unfinished_actions,
                query=self.session_query,
                topic_switched=self.topic_switched)
            self._apply_offloads(mask_res)
            self._decisions.extend(mask_res.decisions)
            self._recalc_budget()
        self._embed_unloaded()   # step 级卸载后立即补算（方案 §0.2）
        return self._obs_result(mask_res)

    def _obs_result(self, mask_res: MaskResult) -> BuildResult:
        masked = [{"id": d.item_id, "reason": d.reason}
                  for d in mask_res.decisions if d.action == ACT_MASK]
        return BuildResult(
            prompt="", used_tokens=self.budget.used,
            max_tokens=self.cfg.max_tokens, masked=masked,
            decisions=list(mask_res.decisions),
            reasons=[str(d) for d in mask_res.decisions])

    def on_turn_end(self, step_count: Optional[int] = None,
                    force: bool = False) -> CompressResult:
        """turn 后钩子：重量级卸载/压缩。全量淘汰决策只能在这里发生。"""
        steps = step_count if step_count is not None else self.turn_steps
        before = self.budget.used
        reason = "turn_end"
        if self.budget.over_trigger or force:
            reason = "budget" if self.budget.over_trigger else "manual"

        # —— 长循环收尾：step 数超阈值 → 折叠成结构化摘要 ——
        folded_ref: Optional[str] = None
        decisions: List[Decision] = []
        if steps > self.cfg.turn_compress_min_steps:
            folded_ref = self._fold_trajectory()
            reason = "long_loop" if reason == "turn_end" else reason
            decisions.append(Decision(
                "trajectory", ACT_COMPRESS,
                f"长循环收尾：{steps} 步 > 阈值 {self.cfg.turn_compress_min_steps}，"
                f"轨迹折叠为结构化摘要 ref={folded_ref}"))

        # —— 预算触发压缩：完整原文→工具结果摘要→状态抽象→元数据/引用 ——
        if self.budget.over_trigger or force or folded_ref:
            offloaded = self._compress(reason)
            decisions.extend(offloaded)

        after = self.budget.used
        self.turn_steps = 0
        self.topic_switched = False
        self._embed_unloaded()   # turn 级卸载/折叠后补算（方案 §0.2）
        return CompressResult(
            reason=reason, before_tokens=before, after_tokens=after,
            offloaded=[d.item_id for d in decisions
                       if d.action in (ACT_OFFLOAD, ACT_EVICT, ACT_COMPRESS)],
            folded=folded_ref, decisions=decisions)

    def compress(self, reason: str = "manual") -> CompressResult:
        """执行压缩并说明压缩原因（供手动/外部调用）。"""
        before = self.budget.used
        decisions = self._compress(reason)
        self._recalc_budget()
        return CompressResult(
            reason=reason, before_tokens=before, after_tokens=self.budget.used,
            offloaded=[d.item_id for d in decisions], decisions=decisions)

    # ─────────────────────────── 内部 ───────────────────────────

    def _sorted_items(self) -> List[ContextItem]:
        att_order = {AttentionPosition.HEAD: 0,
                     AttentionPosition.MIDDLE: 1, AttentionPosition.TAIL: 2}
        return sorted(self.items.values(),
                      key=lambda i: (att_order[i.attention], i.created_step))

    def _recalc_budget(self) -> None:
        used = sum(it.effective_tokens() for it in self.items.values())
        self.budget.update(used, step=self.current_step, event="recalc")

    def _apply_offloads(self, mask_res: MaskResult) -> None:
        """offload 决策 → 内容写外部存储 + 挂引用（可恢复）。"""
        for d in mask_res.decisions:
            if d.action != ACT_OFFLOAD:
                continue
            it = self.items.get(d.item_id)
            if it is None or it.external_ref:
                continue
            # 存原文（masking 前的正文），供 load_by_ref 恢复
            ref = self.store.put(it.content, {"type": it.type.value,
                                              "tool": it.metadata.get("tool", "")})
            it.external_ref = ref
            it.recoverable = True
            it.content = ""          # 索引态不保留正文（规范 §三）

    def _compress(self, reason: str) -> List[Decision]:
        """分层降级卸载：只处理非保护的中段已加载项，逐级降级。"""
        decisions: List[Decision] = []
        if self.budget.used <= self.budget.target_tokens and reason != "manual":
            return decisions
        # 候选：非保护、已加载，按创建时间从旧到新
        cands = [it for it in self.items.values()
                 if not it.is_protected and it.state == LoadState.LOADED
                 and it.attention == AttentionPosition.MIDDLE]
        cands.sort(key=lambda i: i.created_step)
        for it in cands:
            if self.budget.used <= self.budget.target_tokens:
                break
            tier = self._degrade_tier(it)
            before = it.effective_tokens()
            # 任何降级前先保原文到外部（被移除内容必须可恢复）
            if not it.external_ref and it.content:
                it.external_ref = self.store.put(
                    it.content, {"id": it.id, "tier": tier})
                it.recoverable = True
            if tier == "metadata":
                # 最终级：整项出上下文，只留索引 + 外部引用
                if not it.external_ref:
                    ref = self.store.put(it.content, {"id": it.id})
                    it.external_ref = ref
                    it.recoverable = True
                it.state = LoadState.INDEX_ONLY
                it.content = ""
                it.masked = False
                freed = before
                action = ACT_EVICT
                why = f"压缩({reason})：降级为元数据/外部引用"
            elif tier == "summary":
                # 工具结果摘要级
                summary = self._summarize_item(it)
                it.masked = True
                it.mask_reason = f"compress_{reason}"
                it.content = summary
                it.token_count = count_tokens(summary)
                freed = before - it.effective_tokens()
                action = ACT_COMPRESS
                why = f"压缩({reason})：降级为工具结果摘要"
            else:
                it.state = LoadState.INDEX_ONLY
                it.content = ""
                freed = before
                action = ACT_OFFLOAD
                why = f"压缩({reason})：原文卸载到外部存储"
            if it.state == LoadState.INDEX_ONLY and not it.external_ref:
                ref = self.store.put(it.content or it.metadata.get("one_line", ""),
                                     {"id": it.id})
                it.external_ref = ref
                it.recoverable = True
            self.budget.used = max(0, self.budget.used - freed)
            decisions.append(Decision(it.id, action, why))
        self._decisions.extend(decisions)
        return decisions

    def _degrade_tier(self, it: ContextItem) -> str:
        """分层降级选择：summary（工具结果）/ metadata（引用）。"""
        if it.type == ItemType.OBSERVATION and it.metadata.get("one_line"):
            # 还有摘要可留 → 先降 summary；已 masked 过 → 直接 metadata
            return "metadata" if it.masked else "summary"
        return "metadata"

    def _summarize_item(self, it: ContextItem) -> str:
        """工具结果摘要。注入 summarizer（LLM）则用，否则确定性一行。"""
        if self.summarizer is not None:
            try:
                return self.summarizer(it.content)
            except Exception:  # noqa: BLE001 - 摘要失败回落确定性
                pass
        md = it.metadata
        return (f"[压缩摘要] tool={md.get('tool', '?')} "
                f"params={md.get('params_summary', '')} "
                f"tokens={it.token_count} 结果: {md.get('one_line', '')[:200]}")

    def _proactive_prune(self, current_step: int) -> int:
        """turn 内主动卸载（2026-11-13，对齐 Hermes _prune_old_tool_results）。

        ① 去重：同一 tool+params 重复产生的 Observation 只保留最新一条全文，
           旧的降级为一行摘要（Hermes：同文件读 5 次只留最新全文）；
        ② 过期：超过 protect_recent_steps 未被访问的 Observation 降级为一行摘要
           （原文已存外部可恢复）；已是摘要的再降级出上下文（INDEX_ONLY）。
        租约按 max(created_step, last_access_step) 计——召回(load)会续租。
        无 LLM、确定性；与压缩触发无关，不计入压缩次数。返回处理条数。
        """
        n = 0
        # ① 去重（同 tool+params，只留最新）
        groups: Dict[tuple, List[ContextItem]] = {}
        for it in self.items.values():
            if (it.type != ItemType.OBSERVATION or it.state != LoadState.LOADED
                    or it.is_protected):
                continue
            _tool = (it.metadata or {}).get("tool") or ""
            _ps = (it.metadata or {}).get("params_summary") or ""
            if not _tool and not _ps:
                continue
            groups.setdefault((_tool, _ps), []).append(it)
        for lst in groups.values():
            if len(lst) < 2:
                continue
            lst.sort(key=lambda x: x.created_step, reverse=True)
            for older in lst[1:]:
                n += self._unload_obs(older, "重复观察去重（保留最新全文）")
        # ② 过期（租约超龄）
        for it in self.items.values():
            if (it.type != ItemType.OBSERVATION or it.state != LoadState.LOADED
                    or it.is_protected):
                continue
            lease = max(it.created_step, it.last_access_step or 0)
            if current_step - lease > self.cfg.protect_recent_steps:
                n += self._unload_obs(it, "过期观察卸载（原文存外部可恢复）")
        if n:
            self._recalc_budget()
        return n

    def _unload_obs(self, it: ContextItem, why: str) -> bool:
        """观察降级：原文 → 一行摘要 →（已是摘要时）出上下文。降级前原文必存外部。"""
        if it.state != LoadState.LOADED or it.is_protected:
            return False
        if not it.external_ref and it.content:
            it.external_ref = self.store.put(it.content, {"id": it.id})
            it.recoverable = True
        before = it.effective_tokens()
        if not it.masked:
            summary = self._summarize_item(it)
            it.content = summary
            it.masked = True
            it.mask_reason = f"proactive_unload:{why}"
            it.token_count = count_tokens(summary)
            action = ACT_COMPRESS
        else:
            it.content = ""
            it.state = LoadState.INDEX_ONLY
            it.masked = False
            action = ACT_EVICT
        self.budget.used = max(
            0, self.budget.used - (before - it.effective_tokens()))
        self._decisions.append(Decision(it.id, action, f"主动卸载：{why}"))
        return True

    def _fold_trajectory(self) -> str:
        """长循环收尾：任务状态+关键发现+未完成项+外部引用 的结构化摘要。"""
        thoughts = [it for it in self.items.values()
                    if it.type == ItemType.THOUGHT]
        obs = [it for it in self.items.values()
               if it.type == ItemType.OBSERVATION]
        unfinished = sorted(self.unfinished_actions)
        lines = [
            "【任务状态摘要（长循环折叠）】",
            f"总 step 数: {self.turn_steps}",
            f"Thought 数: {len(thoughts)}，Observation 数: {len(obs)}",
            f"未完成项 steps: {unfinished if unfinished else '无'}",
            "关键发现:",
        ]
        for it in obs[-5:]:   # 末 5 条 Observation 的一行摘要
            lines.append(f"- {it.metadata.get('one_line') or it.metadata.get('tool', '')}")
        lines.append("外部引用:")
        for it in obs:
            if it.external_ref:
                lines.append(f"- {it.id} → {it.external_ref}")
        text = "\n".join(lines)
        ref = self.store.put(text, {"kind": "folded_trajectory"})
        # 折叠：旧 Thought/Observation 全部卸载，只留折叠摘要项
        for it in thoughts + obs:
            if it.is_protected or it.id in self.pending_obs:
                continue
            if it.state == LoadState.LOADED and not it.external_ref:
                it.external_ref = self.store.put(
                    it.content, {"id": it.id})
                it.recoverable = True
            it.state = LoadState.INDEX_ONLY
            it.content = ""
            it.masked = False
        fold_item = ContextItem(
            id="folded_summary", type=ItemType.SUMMARY, content=text,
            token_count=count_tokens(text), attention=AttentionPosition.MIDDLE,
            created_step=self.current_step, last_access_step=self.current_step,
            state=LoadState.LOADED, recoverable=True, external_ref=ref,
            persisted=True, pinned=False)
        self.items["folded_summary"] = fold_item
        self._recalc_budget()
        return ref

    def decisions_log(self) -> List[str]:
        """全部可解释记录（项/类型/原因/评分）。"""
        return [str(d) for d in self._decisions]
