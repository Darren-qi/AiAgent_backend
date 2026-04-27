# -*- coding: utf-8 -*-
"""
子团队讨论机制

Supervisor 可以召集2个角色进行内部讨论，讨论过程通过 SSE 推送，
只有结论摘要写入主 GroupChat 历史。
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from app.agent.autogen.team.agents import AGENT_CONFIG

logger = logging.getLogger(__name__)

# 子团队最大轮次
SUB_TEAM_MAX_ROUNDS = 6


class SubTeamDiscussion:
    """
    两个 Agent 之间的内部讨论

    讨论过程：
    1. Agent A 发言
    2. Agent B 回应
    3. 循环直到达成共识或超过最大轮次
    4. 提取结论摘要
    """

    def __init__(
        self,
        agent_a_name: str,
        agent_b_name: str,
        topic: str,
        llm_caller: Callable,          # async (messages, agent_name) -> str
        on_message: Optional[Callable] = None,  # SSE 推送回调
    ):
        self.agent_a = agent_a_name
        self.agent_b = agent_b_name
        self.topic = topic
        self._llm = llm_caller
        self._on_message = on_message
        self.messages: List[Dict[str, str]] = []
        self.channel = f"sub_{agent_a_name.lower()}_{agent_b_name.lower()}"

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._on_message:
            self._on_message(event_type, {**data, "channel": self.channel})

    async def run(self) -> str:
        """执行子团队讨论，返回结论摘要"""
        self._emit("discussion_start", {
            "members": [self.agent_a, self.agent_b],
            "topic": self.topic,
        })

        # 初始化讨论上下文
        system_prompt = (
            f"你们是敏捷团队的 {self.agent_a} 和 {self.agent_b}，"
            f"正在内部讨论：{self.topic}\n"
            "请简洁地交流，达成共识后输出：CONSENSUS: [结论一句话]"
        )
        self.messages = [{"role": "system", "content": system_prompt}]

        current_speaker = self.agent_a
        other_speaker = self.agent_b
        consensus = None

        for round_num in range(SUB_TEAM_MAX_ROUNDS):
            # 当前发言者生成回复
            reply = await self._llm(self.messages, current_speaker)
            self.messages.append({"role": "assistant", "content": f"[{current_speaker}]: {reply}"})

            config = AGENT_CONFIG.get(current_speaker, {})
            self._emit("agent_message", {
                "agent": current_speaker,
                "content": reply,
                "full_content": reply,
                "avatar": config.get("emoji", "🤖"),
                "color": config.get("color", "#f5f5f5"),
                "display_name": config.get("display_name", current_speaker),
                "description": config.get("description", ""),
                "round": round_num + 1,
            })

            # 检测是否达成共识
            if "CONSENSUS:" in reply:
                idx = reply.index("CONSENSUS:")
                consensus = reply[idx + len("CONSENSUS:"):].strip()
                break

            # 交换发言者
            current_speaker, other_speaker = other_speaker, current_speaker

        # 如果没有明确共识，用最后一条消息作为结论
        if not consensus:
            last = self.messages[-1]["content"] if self.messages else "讨论未达成明确结论"
            consensus = last[:300]

        self._emit("discussion_end", {
            "members": [self.agent_a, self.agent_b],
            "topic": self.topic,
            "conclusion": consensus,
        })

        logger.info(f"[SubTeam] {self.agent_a}+{self.agent_b} 讨论完成: {consensus[:80]}")
        return consensus


def parse_sub_team_directive(text: str) -> Optional[Tuple[str, str, str]]:
    """
    解析 Supervisor 输出中的子团队指令

    格式：SUB_TEAM: AgentA+AgentB [讨论主题]
    返回：(agent_a, agent_b, topic) 或 None
    """
    import re
    match = re.search(r"SUB_TEAM:\s*(\w+)\+(\w+)\s+\[([^\]]+)\]", text)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None
