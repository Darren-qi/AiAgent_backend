"""上下文项模型：每个上下文项的完整元数据与两态（索引/全文）。"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ItemType(str, enum.Enum):
    SYSTEM_PROMPT = "system_prompt"      # 系统提示
    CONSTRAINT = "constraint"            # 约束
    USER_REQUEST = "user_request"        # 原始用户请求
    CURRENT_TASK = "current_task"        # 当前任务
    THOUGHT = "thought"                  # Thought
    ACTION = "action"                    # Action
    OBSERVATION = "observation"          # Observation
    KNOWLEDGE = "knowledge"              # 知识
    SUMMARY = "summary"                  # 摘要
    REFERENCE = "reference"              # 引用


class AttentionPosition(str, enum.Enum):
    """注意力位置：开头 / 中段 / 结尾。"""
    HEAD = "head"
    MIDDLE = "middle"
    TAIL = "tail"


class LoadState(str, enum.Enum):
    """两态：只注册轻量索引 vs 加载完整内容。"""
    INDEX_ONLY = "index_only"   # 只保留 id/类型/token估算/外部引用/必要元数据
    LOADED = "loaded"           # 完整正文在上下文中


# 固定保护的类型：永不淘汰
PROTECTED_TYPES = frozenset({
    ItemType.SYSTEM_PROMPT, ItemType.CONSTRAINT,
    ItemType.USER_REQUEST, ItemType.CURRENT_TASK,
})


@dataclass
class ContextItem:
    """规范 §三 要求的全部字段。"""

    id: str                                   # 唯一标识
    type: ItemType
    content: str = ""                         # 完整正文（INDEX_ONLY 时为空）
    token_count: int = 0                      # token 数（全文估算）
    attention: AttentionPosition = AttentionPosition.MIDDLE
    created_step: int = 0                     # 创建 step
    last_access_step: int = 0                 # 最后访问 step
    access_count: int = 0                     # 访问次数
    pinned: bool = False                      # 是否固定保护
    recoverable: bool = False                 # 是否可恢复（有外部引用才能恢复）
    external_ref: str | None = None        # 外部存储引用
    depends_on_steps: list[int] = field(default_factory=list)      # 依赖的 step
    depends_on_items: list[str] = field(default_factory=list)      # 依赖的上下文项
    persisted: bool = False                   # 是否已持久化到环境
    metadata: dict[str, Any] = field(default_factory=dict)
    state: LoadState = LoadState.INDEX_ONLY
    masked: bool = False                      # 是否已被 masking（内容换占位符）
    mask_reason: str = ""

    # —— 便捷判定 ——

    @property
    def is_protected(self) -> bool:
        """固定保护 或 属于受保护类型 → 永不淘汰。"""
        return self.pinned or self.type in PROTECTED_TYPES

    @property
    def is_loaded(self) -> bool:
        return self.state == LoadState.LOADED

    @property
    def placeholder_token_count(self) -> int:
        """masking 后占位符的 token 数（≈1/10 全文，保底 20）。"""
        return max(20, self.token_count // 10)

    def effective_tokens(self) -> int:
        """当前实际占用的 token：未加载=0；masked=占位符；否则全文。"""
        if self.state == LoadState.INDEX_ONLY:
            return 0
        if self.masked:
            return self.placeholder_token_count
        return self.token_count

    def touch(self, step: int) -> None:
        self.last_access_step = step
        self.access_count += 1

    def index_entry(self) -> dict[str, Any]:
        """轻量索引形态：不含正文。"""
        return {
            "id": self.id,
            "type": self.type.value,
            "token_count": self.token_count,
            "attention": self.attention.value,
            "created_step": self.created_step,
            "external_ref": self.external_ref,
            "recoverable": self.recoverable,
            "persisted": self.persisted,
            "metadata": {k: v for k, v in self.metadata.items()
                         if k in ("title", "tool", "summary")},
        }

    def placeholder_text(self) -> str:
        """Observation 占位符：保留工具名、参数摘要、返回 token 数、一行结果摘要。"""
        md = self.metadata
        tool = md.get("tool", "?")
        params = md.get("params_summary", "")
        line = md.get("one_line", "")
        return (f"[已卸载 Observation id={self.id} tool={tool} "
                f"params={params} tokens={self.token_count} 结果: {line}]")
