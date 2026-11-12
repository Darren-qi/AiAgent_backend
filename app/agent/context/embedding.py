"""智谱 embedding-3 客户端（移植自 Agentic Library backend/app/services/zhipu.py:83）。

方案 §2：httpx、批量 64、429/5xx 重试、2048 维校验。
与源的差异（记 CONTEXT_MANAGER_PLAN.md §10 偏差记录）：
- 源为 async（FastAPI 全异步）；embed_fn 插拔位是同步签名 → 本模块同步 httpx，
  阻塞发生在卸载钩子（每批一次 HTTP），async 化留二期。
- 不移植随机投影 project_embedding：那是 pgvector 索引降维；一期是会话内
  内存余弦（方案 §2），直接用全量 2048 维。

Key 来自环境变量 ZHIPU_API_KEY（可显式传入）。未配置时：
- embed()    → 抛 EmbeddingError（直接调用方应显式感知）
- embed_one() → 返回 None（EmbedFn 插拔位：向量层优雅跳过，不阻塞主流程）
"""
from __future__ import annotations

import logging
import os
import time
from typing import List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "embedding-3"
DEFAULT_DIMENSION = 2048
DEFAULT_BATCH_SIZE = 64

__all__ = ["EmbeddingError", "ZhipuEmbedder"]


class EmbeddingError(RuntimeError):
    """embedding 请求/响应异常（未配置 key、HTTP 错误、响应格式/维数不符）。"""


class ZhipuEmbedder:
    """智谱 embedding-3 同步客户端：批量 64/次、429与5xx 重试、2048 维校验。"""

    def __init__(self, api_key: Optional[str] = None, *,
                 base_url: Optional[str] = None,
                 model: str = DEFAULT_MODEL,
                 dimension: int = DEFAULT_DIMENSION,
                 batch_size: int = DEFAULT_BATCH_SIZE,
                 timeout: float = 60.0,
                 max_retries: int = 3,
                 backoff: float = 0.1,
                 transport: Optional[httpx.BaseTransport] = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("ZHIPU_API_KEY", "")
        # 独立环境变量，避免与聊天用 ZHIPU_BASE_URL（无 /api/paas/v4 后缀）冲突
        self.base_url = (base_url or os.environ.get("ZHIPU_EMBED_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model
        self.dimension = dimension
        self.batch_size = batch_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._transport = transport   # 测试注入 httpx.MockTransport

    # —— 公开接口 ——

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        """批量 embedding（顺序与输入一致）。失败抛 EmbeddingError。"""
        if not texts:
            return []
        if not self.api_key:
            raise EmbeddingError("ZHIPU_API_KEY 未配置")
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start:start + self.batch_size])
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_one(self, text: str) -> Optional[List[float]]:
        """EmbedFn 插拔位：单条 embedding；任何失败返回 None（跳过向量层）。"""
        if not text or not self.api_key:
            return None
        try:
            return self.embed([text])[0]
        except EmbeddingError as exc:
            logger.warning("embedding 失败，跳过向量层：%s", exc)
            return None

    # —— 内部 ——

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    @staticmethod
    def _retryable(status: int) -> bool:
        return status == 429 or status >= 500

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        url = f"{self.base_url}/embeddings"
        payload = {"model": self.model, "input": batch}
        last_err = "unknown"
        for attempt in range(self.max_retries + 1):
            if attempt and self.backoff:
                time.sleep(self.backoff * attempt)
            try:
                with httpx.Client(timeout=self.timeout,
                                  transport=self._transport) as client:
                    resp = client.post(url, headers=self._headers(), json=payload)
            except httpx.HTTPError as exc:
                last_err = f"网络错误: {exc}"
                continue
            if self._retryable(resp.status_code):
                last_err = f"HTTP {resp.status_code}"
                continue
            if resp.status_code != 200:
                raise EmbeddingError(f"HTTP {resp.status_code}")
            try:
                body = resp.json()
            except ValueError as exc:
                raise EmbeddingError("响应不是合法 JSON") from exc
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list) or len(data) != len(batch):
                raise EmbeddingError("embedding_response_count_mismatch")
            try:
                ordered = sorted(data, key=lambda d: int(d["index"]))
                vectors = [d["embedding"] for d in ordered]
            except (KeyError, TypeError, ValueError) as exc:
                raise EmbeddingError("embedding_invalid_response") from exc
            if any(not isinstance(v, list) or len(v) != self.dimension
                   for v in vectors):
                raise EmbeddingError(
                    f"embedding_dimension_mismatch（期望 {self.dimension} 维）")
            return vectors
        raise EmbeddingError(f"重试 {self.max_retries} 次仍失败: {last_err}")
