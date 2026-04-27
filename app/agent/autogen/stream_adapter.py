# -*- coding: utf-8 -*-
"""
SSE 流适配器

将 AgentTeam 的事件回调转换为 FastAPI SSE 事件流。
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

# 导入agent配置
try:
    from app.agent.autogen.team.agents import AGENT_CONFIG
except ImportError:
    # 回退配置
    AGENT_CONFIG = {}

logger = logging.getLogger(__name__)


class SSEStreamAdapter:
    """
    将 AutoGen 团队事件转换为 SSE 格式的异步事件流。

    使用方式：
        adapter = SSEStreamAdapter()
        # 将 adapter.on_event 作为回调传入 session_manager.execute
        async for sse_line in adapter.stream():
            yield sse_line
    """

    def __init__(self, max_queue_size: int = 200):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._done = False

    def on_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        事件回调（同步），由 AgentTeam 内部调用。
        将事件放入队列，供 stream() 异步消费。
        """
        try:
            self._queue.put_nowait({"type": event_type, "data": data})
        except asyncio.QueueFull:
            logger.warning(f"[SSEAdapter] 队列已满，丢弃事件: {event_type}")

    def close(self) -> None:
        """标记流结束"""
        self._done = True
        try:
            self._queue.put_nowait(None)  # 哨兵值
        except asyncio.QueueFull:
            pass

    async def stream(self) -> AsyncIterator[str]:
        """
        异步生成器：逐条 yield SSE 格式字符串。

        SSE 格式：
            data: {"type": "...", "data": {...}}\n\n
        """
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # 心跳：避免客户端超时断连
                yield ": heartbeat\n\n"
                continue

            if item is None:
                # 收到哨兵，结束流
                yield f"data: {json.dumps({'type': 'stream_end'}, ensure_ascii=False)}\n\n"
                break

            try:
                payload = json.dumps(item, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            except (TypeError, ValueError) as e:
                logger.error(f"[SSEAdapter] 序列化失败: {e}, item={item}")


# ── 事件格式化辅助函数 ──────────────────────────────────────

def format_agent_message(agent: str, content: str, full_content: str = "", iteration: int = 0, channel: str = "main") -> Dict:
    """格式化 agent 消息事件"""
    # 获取agent配置
    config = AGENT_CONFIG.get(agent, {})

    # 从 full_content 中提取 ## 对话 部分作为消息摘要
    display_content = content
    if full_content:
        # 尝试从完整内容中提取 ## 对话 部分
        import re
        dialogue_match = re.search(r'## 对话\s*\n(.*?)(?=\n## |\Z)', full_content, re.DOTALL)
        if dialogue_match:
            display_content = dialogue_match.group(1).strip()
            # 如果提取的对话内容太短或为空，使用原始content
            if len(display_content) < 5:
                display_content = content
        else:
            display_content = content

    return {
        "type": "agent_message",
        "data": {
            "agent": agent,
            "content": display_content,
            "full_content": full_content if full_content else content,
            "avatar": config.get("emoji", "🤖"),
            "color": config.get("color", "#f5f5f5"),
            "display_name": config.get("display_name", agent),
            "description": config.get("description", ""),
            "iteration": iteration,
            "channel": channel,
        }
    }


def format_thinking(agent: str, iteration: int = 0) -> Dict:
    """格式化 agent 思考中事件"""
    return {
        "type": "agent_thinking",
        "data": {"agent": agent, "iteration": iteration}
    }


def format_error(agent: str, error: str) -> Dict:
    """格式化错误事件"""
    return {
        "type": "error",
        "data": {"agent": agent, "error": error}
    }


def format_done(summary: str, iterations: int) -> Dict:
    """格式化任务完成事件"""
    return {
        "type": "done",
        "data": {"summary": summary, "iterations": iterations}
    }
