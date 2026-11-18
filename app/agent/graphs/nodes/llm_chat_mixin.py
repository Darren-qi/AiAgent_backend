"""节点公用 Mixin：带取消语义的 LLM 调用。

此前 Planner / Integrator / IntentDetector 各自复制了一份完全相同的
_llm_chat，收敛到这里。
"""

from typing import Any


class LLMChatMixin:
    """统一 _llm_chat 入口：自动携带 task_id 以支持取消。

    宿主类需提供：
        self._task_id   任务 ID（None/空 表示无取消上下文）
        self.llm_factory  LLM 工厂，提供 chat(messages, **kwargs)
    """

    _task_id: Any
    llm_factory: Any

    async def _llm_chat(self, messages: list, **kwargs: Any):
        """统一 LLM 调用方法，自动传递 task_id 以支持取消"""
        if self._task_id:
            kwargs["task_id"] = self._task_id
        return await self.llm_factory.chat(messages, **kwargs)
