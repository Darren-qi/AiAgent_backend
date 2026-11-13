"""上下文上限对齐 deepseek-chat 窗口 128K + 恰好用满才触发压缩（2026-11-12 方案B，同日 150K→128K 修订）。

验证点：
1. ContextConfig / Settings 默认 128000、trigger=1.0，validate() 通过
2. BudgetTracker 边界：恰好 128000 不触发，128001 触发
3. 未超限 turn_end 不压缩（= 不计压缩次数，与 main_graph 计数条件一致）
"""
from app.agent.context.budget import BudgetTracker
from app.agent.context.config import ContextConfig
from app.agent.context.manager import ContextManager


def test_context_config_default_128k():
    cfg = ContextConfig()
    assert cfg.max_tokens == 128000
    assert cfg.compress_trigger_ratio == 1.0
    cfg.validate()  # target 0.5 < trigger 1.0 必须合法


def test_settings_default_128k():
    from app.core.config import get_settings
    s = get_settings()
    assert s.context_max_tokens == 128000
    assert s.context_compress_trigger_ratio == 1.0
    cc = s.build_context_config()
    assert cc.max_tokens == 128000
    assert cc.compress_trigger_ratio == 1.0


def test_trigger_only_over_128k():
    b = BudgetTracker(max_tokens=128000, trigger_ratio=1.0)
    b.update(128000, step=1)
    assert not b.over_trigger, "恰好 128K 不算超限"
    b.update(128001, step=2)
    assert b.over_trigger, "超过 128K 必须触发"


def test_turn_end_under_limit_no_compress():
    """未超限 → on_turn_end 不产生卸载/折叠 → main_graph 不 +1 压缩次数。"""
    mgr = ContextManager(cfg=ContextConfig())
    mgr.on_session_start(system_prompt="sys", constraints="", user_request="q")
    cr = mgr.on_turn_end()
    assert not cr.offloaded
    assert not cr.folded
    assert cr.reason == "turn_end"
