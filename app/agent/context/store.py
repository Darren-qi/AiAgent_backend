"""外部存储：卸载内容的保存与按引用恢复。内存兜底，可插拔。"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Protocol


class ExternalStore(Protocol):
    """外部存储协议——后续可接 pgsaver / 文件 / 向量库。"""

    def put(self, content: str, meta: dict | None = None) -> str: ...
    def get(self, ref: str) -> str | None: ...
    def exists(self, ref: str) -> bool: ...


@dataclass
class MemoryStore:
    """内存存储兜底（规范 §五B：无外部存储实现时使用）。"""

    _data: dict[str, str] = field(default_factory=dict)
    _meta: dict[str, dict] = field(default_factory=dict)
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    def put(self, content: str, meta: dict | None = None) -> str:
        ref = f"mem://{int(time.time() * 1000)}/{next(self._seq)}"
        self._data[ref] = content
        if meta:
            self._meta[ref] = meta
        return ref

    def get(self, ref: str) -> str | None:
        return self._data.get(ref)

    def exists(self, ref: str) -> bool:
        return ref in self._data

    def meta(self, ref: str) -> dict:
        return self._meta.get(ref, {})


class PgSaverStore:
    """基于 PostgresSaver 的持久化存储（接线用，构造时注入 saver）。

    session_id 通过 ref 编码携带（pgsaver://<session_id>/<seq>），
    避免调用方额外传参；value 存 JSON {content, meta}。
    """

    def __init__(self, saver, session_id: str = "context") -> None:
        self._saver = saver
        self._default_sid = session_id
        self._seq = itertools.count(1)

    def put(self, content: str, meta: dict | None = None) -> str:
        import json
        sid = (meta or {}).get("session_id", self._default_sid)
        ref = f"pgsaver://{sid}/{next(self._seq)}"
        self._saver.save_working(
            session_id=sid,
            memory_key=ref,
            value=json.dumps({"content": content, "meta": meta or {}},
                             ensure_ascii=False),
        )
        return ref

    def get(self, ref: str) -> str | None:
        import json
        parts = ref.split("/")
        sid = parts[-2] if len(parts) >= 2 else self._default_sid
        raw = self._saver.get_working_sync(session_id=sid, memory_key=ref)
        if not raw:
            return None
        try:
            return json.loads(raw).get("content")
        except (ValueError, TypeError):
            return None

    def exists(self, ref: str) -> bool:
        return self.get(ref) is not None


_STORES: dict[str, ExternalStore] = {}


def get_store(kind: str = "memory") -> ExternalStore:
    """按配置取存储实现；未知类型回落内存兜底。"""
    if kind == "memory":
        if "memory" not in _STORES:
            _STORES["memory"] = MemoryStore()
        return _STORES["memory"]
    # pgsaver 等需注入 saver 的实现由调用方 register_store 注册
    return _STORES.get(kind) or _STORES.setdefault("memory", MemoryStore())


def register_store(kind: str, store: ExternalStore) -> None:
    _STORES[kind] = store
