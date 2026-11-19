"""可插拔上下文管理器（ContextManager）。

规则与配置见 README_CONTEXT.md；方案比对文件见项目根 CONTEXT_MANAGER_PLAN.md。
"""
from .budget import BudgetTracker, calibrate, calibration_ratio, count_tokens, reset_calibration
from .config import ContextConfig, RecallConfig
from .embedding import EmbeddingError, ZhipuEmbedder
from .items import PROTECTED_TYPES, AttentionPosition, ContextItem, ItemType, LoadState
from .manager import BuildResult, CompressResult, ContextManager
from .masking import Decision, MaskResult, StepLevelUnloader
from .recall import RecallEngine, RecallResult
from .scoring import ScoreBreakdown, Scorer, cosine
from .store import ExternalStore, MemoryStore, get_store, register_store

__all__ = [
    "AttentionPosition", "BuildResult", "BudgetTracker", "CompressResult",
    "ContextConfig", "ContextItem", "ContextManager", "Decision",
    "EmbeddingError", "ExternalStore", "ItemType", "LoadState", "MaskResult",
    "MemoryStore", "PROTECTED_TYPES", "RecallConfig", "RecallEngine",
    "RecallResult", "ScoreBreakdown", "Scorer", "StepLevelUnloader",
    "ZhipuEmbedder", "calibrate", "calibration_ratio", "count_tokens",
    "cosine", "get_store", "register_store", "reset_calibration",
]
