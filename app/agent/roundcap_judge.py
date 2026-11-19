"""30 轮上限:截断后的续跑判断与终稿提示。"""
import json
import logging
import re

from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

NOTICE = "已达30轮上限"

HINT = "已达30轮上限,本轮强制结束;如需继续执行,请输入:继续执行"

async def judge_continue(task: str, prior: str) -> bool:
    """LLM 判断新消息是否意在继续被中断的任务(失败默认继续)。"""
    try:
        logger.info("[roundcap] judge start task=%s", task[:40])
        r = await LLMFactory.get_instance().chat(
            messages=[{"role": "user", "content": (
                "只输出JSON:{\"continue\": true或false}。判断用户新消息是否意在继续之前被中断的任务。" 
                "上轮状态:" + (prior or "")[:500] + " 新消息:" + task)}],
            model=None, strategy="cost", temperature=0.1, max_tokens=80)
        m = re.search(r"\{[\s\S]*\}", r.content or "")
        res = bool(json.loads(m.group()).get("continue", True)) if m else True
        logger.info("[roundcap] judge result=%s", res)
        return res
    except Exception as e:
        logger.warning("[roundcap] judge failed: %s", e)
        return True

async def cap_restore(sm, task: str, restored: bool):
    """恢复态断点判断（2026-11-14 用户定：截断续跑与失败收尾都支持断点继续）。

    触发条件=截断(轮次用尽) 或 上轮失败收尾(failed_error 非空)：
    继续 -> 截断续预算 + 复位失败待办后续跑；新任务 -> 丢弃断点(返回 None)。
    普通恢复态(如用户取消)不惊动 judge，沿用原直通语义。
    """
    if not (restored and sm is not None):
        return sm, restored
    capped = sm.iteration >= sm.max_iterations
    failed = bool(getattr(sm, "failed_error", ""))
    if not (capped or failed):
        return sm, restored
    # 失败但全部待办已完成 = 没有可续的断点（失败点在产出验收），
    # 交给下一轮新规划，不惊动 judge
    if failed and all(getattr(t, "status", "") == "completed" for t in (sm.todos or [])):
        logger.info("[roundcap] failed state has no pending work, discard")
        return None, False
    prior = sm.scratchpad or ""
    if failed:
        prior = "上轮任务失败收尾，错误:" + str(sm.failed_error)[:200] + chr(10) + prior
    if await judge_continue(task, prior):
        if capped:
            sm.extend_budget()
        if hasattr(sm, "prepare_resume"):
            sm.prepare_resume()
        logger.info("[roundcap] resume: capped=%s failed=%s budget=%s",
                    capped, failed, sm.max_iterations)
        return sm, restored
    logger.info("[roundcap] discard state, new task")
    return None, False

def cap_notice(result, state):
    """轮次上限截断时给终稿追加可继续提示。"""
    ctx = getattr(state, "context", None) or {}
    if ctx.get("_rounds_capped") and isinstance(result, str):
        return result + chr(10) + chr(10) + HINT
    return result
