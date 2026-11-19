"""LLM 工厂类"""

from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── 真实 usage 追踪（P1/P2，2026-11-14）─────────────────────────────
# ① 每次 LLM 调用返回后用真实 prompt_tokens 校准 tiktoken 估算
#    （calibrate 此前只有定义和测试、生产零调用点 → 比例恒 1.0）；
# ② 按 scope 累计本 turn 计费量 {input, output, cost, calls, peak_in}，
#    供 context_usage 事件对账 DeepSeek 后台账单。
# scope 由 main_graph 每 turn 开始时 set_usage_scope(task_id or session_id)，
# factory 侧优先取 scope（task_id 可能为 None 或残留上轮值），保证与 reset 同 key。
# 全部 try/except 兜底：追踪失败绝不影响 LLM 调用本身。
import contextvars

from app.agent.llm.budget_manager import BudgetManager
from app.agent.llm.router import ModelRouter
from app.agent.llm.types import ChatRequest, LLMResponse, ModelProvider

_usage_scope: contextvars.ContextVar = contextvars.ContextVar(
    "llm_usage_scope", default="")
_TASK_USAGE: dict[str, dict[str, Any]] = {}
_LAST_USAGE: dict[str, Any] = {
    "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}


def set_usage_scope(scope: str) -> None:
    """turn 开始时设定本 turn 的累计 key（task_id 优先，缺省 session_id）。"""
    _usage_scope.set(scope or "")


def reset_task_usage(scope: str | None = None) -> None:
    """清零某 scope 的累计（不传则用当前 scope；key 缺省回落 global）。"""
    key = scope or _usage_scope.get() or "global"
    _TASK_USAGE[key] = {"prompt_tokens": 0, "completion_tokens": 0,
                        "cost": 0.0, "calls": 0, "peak_in": 0}


def get_task_usage(scope: str | None = None) -> dict[str, Any]:
    """读某 scope 的本 turn 累计（不传则用当前 scope）。"""
    key = scope or _usage_scope.get() or "global"
    return dict(_TASK_USAGE.get(key) or {"prompt_tokens": 0,
                                         "completion_tokens": 0,
                                         "cost": 0.0, "calls": 0, "peak_in": 0})


def get_last_usage() -> dict[str, Any]:
    """最近一次 LLM 调用的真实 usage（跨 scope）。"""
    return dict(_LAST_USAGE)


class LLMFactory:
    """LLM 工厂类 - 统一管理所有模型提供商"""

    _instance: Optional["LLMFactory"] = None
    _providers: dict[ModelProvider, type] = {}

    @classmethod
    def get_instance(cls, config: dict[str, Any] | None = None) -> "LLMFactory":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls(config)
        elif config and not cls._instance._initialized:
            cls._instance.__init__(config)
        return cls._instance

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: dict[str, Any] | None = None):
        if self._initialized:
            return

        self.config = config or {}
        self.router = ModelRouter(self.config)
        self.budget_manager = BudgetManager()

        self._providers = {}
        self._provider_instances: dict[ModelProvider, Any] = {}

        self._register_providers()
        self._initialized = True

    def _register_providers(self) -> None:
        """注册所有提供商"""
        from app.agent.llm.providers.anthropic import AnthropicProvider
        from app.agent.llm.providers.deepseek import DeepSeekProvider
        from app.agent.llm.providers.gemini import GeminiProvider
        from app.agent.llm.providers.kimi import KimiProvider
        from app.agent.llm.providers.minimax import MiniMaxProvider
        from app.agent.llm.providers.ollama import OllamaProvider
        from app.agent.llm.providers.openai import OpenAIProvider
        from app.agent.llm.providers.zhipu import ZhipuProvider

        self._providers = {
            ModelProvider.DEEPSEEK: DeepSeekProvider,
            ModelProvider.KIMI: KimiProvider,
            ModelProvider.ZHIPU: ZhipuProvider,
            ModelProvider.OPENAI: OpenAIProvider,
            ModelProvider.ANTHROPIC: AnthropicProvider,
            ModelProvider.GEMINI: GeminiProvider,
            ModelProvider.OLLAMA: OllamaProvider,
            ModelProvider.MINIMAX: MiniMaxProvider,
        }

    def get_provider(self, provider: ModelProvider) -> Any:
        """获取提供商实例"""
        if provider not in self._provider_instances:
            provider_class = self._providers.get(provider)
            if not provider_class:
                raise ValueError(f"不支持的提供商: {provider}")

            models = self.router.get_available_models()
            model_config = next((m for m in models if m.provider == provider), None)

            if not model_config:
                raise ValueError(f"未配置 {provider.value} 模型")

            self._provider_instances[provider] = provider_class(model_config)

        return self._provider_instances[provider]

    async def chat(
        self,
        messages: list,
        model: str | None = None,
        strategy: str | None = None,
        task_id: str | None = None,
        **kwargs
    ) -> LLMResponse:
        """发送聊天请求（支持可取消）"""
        from app.agent.cancel_signal import cancel_signal, cancellable_chat
        from app.agent.llm.types import ChatMessage

        chat_messages = [
            ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
            for m in messages
        ]

        request = ChatRequest(
            messages=chat_messages,
            model=model,
            **{k: v for k, v in kwargs.items() if k not in ("model",)}
        )

        selected_model = None

        if model:
            models = self.router.get_available_models()
            selected_model = next((m for m in models if m.name == model), None)

        if not selected_model:
            selected_model = self.router.select_model(strategy=strategy)

        if not selected_model:
            raise RuntimeError("没有可用的模型")

        # 用户级 DeepSeek key（2026-11-14）：本 turn 用户填了自己的 key →
        # 注入 request，provider 侧按 key 走用户自己的 client 计费。
        # 未填（空串）→ 不注入，回落系统 key。
        if selected_model.provider == ModelProvider.DEEPSEEK:
            from app.agent.llm.user_api_key import get_user_api_key
            _uk = get_user_api_key()
            if _uk:
                request.api_key = _uk

        estimated_cost = (selected_model.input_cost_per_1k + selected_model.output_cost_per_1k) / 2 * 1000
        allowed, status = await self.budget_manager.check_budget(estimated_cost)

        if not allowed:
            raise RuntimeError(f"预算不足，当前状态: {status.value}")

        provider = self.get_provider(selected_model.provider)

        # 获取超时时间（从 request 中或使用默认值）
        # 注意：LLM 调用可能需要较长时间，设置为 120 秒
        timeout = getattr(request, 'timeout', None) or 120.0

        # 捕获 budget_manager 引用，用于工厂函数
        budget_manager = self.budget_manager

        async def _do_chat():
            nonlocal provider, request
            import time as _time
            _t0 = _time.perf_counter()
            result = await provider.chat(request)
            _latency_ms = round((_time.perf_counter() - _t0) * 1000, 1)
            pi = co = 0
            try:
                # P1（2026-11-14）：真实 usage → 校准估算 + 本 turn 计费累计。
                # 追踪任何一步失败都只跳过追踪，绝不影响调用返回。
                u = result.usage or {}
                pi = int(u.get("prompt_tokens") or 0)
                co = int(u.get("completion_tokens") or 0)
                if pi > 0:
                    from app.agent.context.budget import calibrate, count_tokens
                    est = 0
                    for m in request.messages:
                        est += count_tokens(
                            getattr(m, "content", "") or "", calibrated=False)
                    calibrate(pi, max(est, 1))
                key = _usage_scope.get() or task_id or "global"
                acc = _TASK_USAGE.setdefault(
                    key, {"prompt_tokens": 0, "completion_tokens": 0,
                          "cost": 0.0, "calls": 0, "peak_in": 0})
                acc["prompt_tokens"] += pi
                acc["completion_tokens"] += co
                acc["cost"] = float(acc.get("cost") or 0.0) + float(result.cost or 0.0)
                acc["calls"] += 1
                acc["peak_in"] = max(int(acc.get("peak_in") or 0), pi)
                _LAST_USAGE.update({"prompt_tokens": pi,
                                    "completion_tokens": co,
                                    "cost": float(result.cost or 0.0)})
            except Exception:  # noqa: BLE001 - 用量追踪永不阻塞 LLM 调用
                pass

            # 阶段六：LLM 层打点——app.log（loguru→文件，含 model/latency）
            # + JSONL run 日志；任何失败只降级不阻塞调用返回。
            try:
                from app.agent.trace import run_log
                from app.utils.logger import get_logger
                _model = (getattr(result, "model", None)
                          or (selected_model.name if selected_model else "-"))
                _provider = str(getattr(result, "provider", None)
                                or getattr(selected_model, "provider", ""))
                get_logger().info(
                    f"[LLM] model={_model} provider={_provider} "
                    f"latency_ms={_latency_ms} prompt_tokens={pi} "
                    f"completion_tokens={co} "
                    f"cost={float(result.cost or 0.0):.6f}")
                run_log("llm_call", model=_model, provider=_provider,
                        latency_ms=_latency_ms, prompt_tokens=pi,
                        completion_tokens=co,
                        cost=float(result.cost or 0.0))
            except Exception:  # noqa: BLE001 - 打点永不阻塞
                pass

            await budget_manager.record_usage(result.cost)
            return result

        # 如果有 task_id 且未被取消，使用可取消的调用
        if task_id and not cancel_signal.is_cancelled(task_id):
            response = await cancellable_chat(
                coro_factory=_do_chat,
                task_id=task_id,
                timeout=timeout,
            )
        else:
            response = await _do_chat()

        return response

    def get_available_models(self) -> list:
        """获取可用模型列表"""
        return self.router.get_available_models()

    def get_budget_status(self):
        """获取预算状态"""
        return self.budget_manager.get_status()
