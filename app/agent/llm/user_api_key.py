"""用户级 DeepSeek API Key（2026-11-14）。

用户在「设置 → 通用设置」填写自己的 DeepSeek key 后持久存
users.deepseek_api_key；该用户在 LangGraph 后端的所有 LLM 调用
改走用户自己的 key 计费。未填 / 查询失败一律回落系统 key
（.env DEEPSEEK_API_KEY），装载失败绝不阻塞任务执行。

设计：每 turn 开始（main_graph.execute，与 usage scope 同点）按
session_id 查 key 并 set 进 contextvar，factory.chat 在 DeepSeek
选型时读取并注入 ChatRequest.api_key，provider 侧按 key 复用
专属 client。contextvar 按 asyncio task 隔离，多用户并发互不串。
"""

import contextvars
from typing import Optional, Tuple

# 本 turn（task）的用户 DeepSeek key；空串 = 用系统 key。
_user_api_key: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_deepseek_api_key", default="")


def set_user_api_key(key: Optional[str]) -> None:
    """设定本 turn 的用户 key（空串/None = 清除，回落系统 key）。"""
    _user_api_key.set((key or "").strip())


def get_user_api_key() -> str:
    """读当前 turn 的用户 key（无则空串）。"""
    return _user_api_key.get()


def mask_key(key: Optional[str]) -> str:
    """掩码显示：sk-abcdef123456 → sk-***3456；短于8位 → ***；空 → ''。"""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) < 8:
        return "***"
    return f"{k[:3]}***{k[-4:]}"


async def load_user_deepseek_key(session_id: Optional[str]) -> str:
    """按 session → user 查用户自己的 key；查不到 / 任何失败返回 ''。"""
    if not session_id:
        return ""
    try:
        from sqlalchemy import select
        from app.db.session import AsyncSessionLocal
        from app.models.experience import SessionModel
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(SessionModel.user_id, User.deepseek_api_key)
                .join(User, User.id == SessionModel.user_id)
                .where(SessionModel.session_id == session_id)
            )).first()
            if not row:
                return ""
            return (row[1] or "").strip()
    except Exception:  # noqa: BLE001 - 查 key 失败只降级系统 key
        return ""


async def apply_turn_user_api_key(session_id: Optional[str]) -> None:
    """每 turn 开始时装载本 turn 的用户 key；失败清空（回落系统 key）。"""
    try:
        set_user_api_key(await load_user_deepseek_key(session_id))
    except Exception:  # noqa: BLE001
        set_user_api_key("")


async def validate_deepseek_key(key: str) -> Tuple[bool, str]:
    """保存前用 DeepSeek GET /models（免费、轻量）验证 key。

    返回 (是否有效, 错误信息)。网络异常也拒绝保存，避免存入坏 key。
    """
    import httpx

    key = (key or "").strip()
    if not key:
        return False, "Key 为空"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.deepseek.com/models",
                headers={"Authorization": f"Bearer {key}"},
            )
    except Exception as e:  # noqa: BLE001
        return False, f"网络异常，请稍后重试（{type(e).__name__}）"
    if resp.status_code in (401, 403):
        return False, "Key 无效"
    if resp.status_code != 200:
        return False, f"验证失败（HTTP {resp.status_code}）"
    return True, ""
