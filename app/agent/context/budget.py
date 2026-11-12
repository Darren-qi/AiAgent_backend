"""token 预算：tiktoken 精确计数 + 预算比例追踪。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 - tiktoken 缺失时降级估算
    _ENC = None


# API usage 校准比例（方案 §2：事前 tiktoken 估算，事后按 API 真实
# prompt_tokens 校准——glm 分词与 cl100k 不同，需比例修正）
_calibration_ratio = 1.0


def calibrate(actual: int, estimated: int) -> float:
    """用 API 返回的真实 prompt_tokens(actual) 校准 tiktoken 估算(estimated)。

    两者任一非正 → 忽略本次样本；返回当前比例（最后一次有效样本生效）。
    """
    global _calibration_ratio
    if actual > 0 and estimated > 0:
        _calibration_ratio = actual / estimated
    return _calibration_ratio


def calibration_ratio() -> float:
    """当前校准比例（1.0 = 未校准）。"""
    return _calibration_ratio


def reset_calibration() -> None:
    """恢复未校准状态（测试/新会话用）。"""
    global _calibration_ratio
    _calibration_ratio = 1.0


def count_tokens(text: str) -> int:
    """token 计数：tiktoken 优先，缺失时 chars/4 估算（CJK 加权）；按校准比例修正。"""
    if not text:
        return 0
    raw = 0
    if _ENC is not None:
        try:
            raw = len(_ENC.encode(text, disallowed_special=()))
        except Exception:  # noqa: BLE001
            raw = 0
    if not raw:
        # 降级：ASCII 约 4 字符/token，CJK 约 1.5 字符/token
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        other = len(text) - cjk
        raw = max(1, cjk * 2 // 3 + other // 4)
    return max(1, int(round(raw * _calibration_ratio)))


@dataclass
class BudgetTracker:
    """按比例触发的预算追踪（max_tokens × ratio）。"""

    max_tokens: int
    trigger_ratio: float = 0.7
    target_ratio: float = 0.5
    used: int = 0
    history: list = field(default_factory=list)  # (step, used, event)

    @property
    def trigger_tokens(self) -> int:
        return int(self.max_tokens * self.trigger_ratio)

    @property
    def target_tokens(self) -> int:
        return int(self.max_tokens * self.target_ratio)

    @property
    def usage_ratio(self) -> float:
        return self.used / self.max_tokens if self.max_tokens else 0.0

    @property
    def over_trigger(self) -> bool:
        return self.used > self.trigger_tokens

    def update(self, used: int, step: int = 0, event: str = "") -> None:
        self.used = used
        self.history.append((step, used, event))

    def after_compress(self, step: int = 0) -> None:
        """压缩后记录回到 target 附近。"""
        self.history.append((step, self.used, "compressed"))
