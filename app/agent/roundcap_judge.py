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
    """已被轮次上限截断的恢复态:继续->续预算;新任务->丢弃(返回None)。"""
    if not (restored and sm is not None and sm.iteration >= sm.max_iterations):
        return sm, restored
    if await judge_continue(task, sm.scratchpad or ""):
        sm.extend_budget()
        logger.info("[roundcap] extend budget -> %s", sm.max_iterations)
        return sm, restored
    logger.info("[roundcap] discard state, new task")
    return None, False

def cap_notice(result, state):
    """轮次上限截断时给终稿追加可继续提示。"""
    ctx = getattr(state, "context", None) or {}
    if ctx.get("_rounds_capped") and isinstance(result, str):
        return result + chr(10) + chr(10) + HINT
    return result
