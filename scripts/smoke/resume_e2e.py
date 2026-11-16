"""TC-S16-03 端到端：失败断点 → 发「继续」→ 断点续跑 + edit files[] 批量执行。

流程（对应 TESTCASES.md TC-S16-03 的手动步骤自动化）：
  1. 真实跑第1轮建任务目录 + note.txt（建立 task_path）
  2. 规范化 note.txt 内容，用与失败收尾相同的 note_failure+save_state 播种失败断点
  3. 第2轮只发「继续」→ 期望：resumed 事件、断点待办被执行、
     edit 的 files:[{path,old_string,new_string}] 批量生效（现场根因回归）、
     成功收尾清掉断点、全程无"缺少 path 参数"

运行（backend 目录）: ./.venv/bin/python scripts/smoke/resume_e2e.py
"""
import asyncio
import pathlib
import time

BASE = "http://127.0.0.1:8000"


async def main():
    import logging
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)

    from app.core.security import create_access_token
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text("SELECT id, username FROM users ORDER BY id LIMIT 1"))).all()
    token = create_access_token(str(rows[0][0]))
    sid = f"e2e_resume_{int(time.time())}"
    print(f"user={rows[0][1]} session={sid}")

    import aiohttp
    hdr = {"Authorization": f"Bearer {token}"}

    async def run_turn(task: str, title: str):
        events = []
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{BASE}/api/v1/agent/execute/stream",
                json={"session_id": sid, "task": task, "title": title},
                headers=hdr,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                print(f"[{title}] HTTP {resp.status}")
                buf = ""
                async for chunk in resp.content.iter_any():
                    buf += chunk.decode("utf-8", "replace")
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        etype, data = "", ""
                        for ln in block.split("\n"):
                            if ln.startswith("event:"):
                                etype = ln[6:].strip()
                            elif ln.startswith("data:"):
                                data = ln[5:].strip()
                        if etype:
                            events.append((etype, data))
                            if etype in ("complete", "error", "stopped"):
                                break
                    if events and events[-1][0] in ("complete", "error", "stopped"):
                        break
        return events

    # ---- 第1轮：建立任务目录与目标文件 ----
    ev1 = await run_turn("在任务目录创建 note.txt，内容为 hi", "E2E-断点-轮1")
    print("轮1 事件:", [e for e, _ in ev1])
    assert ev1 and ev1[-1][0] == "complete", f"轮1未正常完成: {ev1[-3:]}"

    from app.api.v1.endpoints.agent import get_session
    res = await get_session(session_id=sid, user=None)
    tp = (res.get("data") or {}).get("task_path")
    print("task_path:", tp)
    assert tp, "轮1后必须解析出 task_path"

    from app.agent.skills.file_operations.skill import get_tasks_dir
    target = get_tasks_dir() / tp / "note.txt"
    assert target.exists(), f"目标文件不存在: {target}"
    target.write_text("hi", encoding="utf-8")  # 规范化，去 LLM 内容不确定性

    # ---- 播种失败断点（与失败收尾完全相同的 note_failure + save_state） ----
    from app.agent.execution_state import ExecutionStateManager
    sm = ExecutionStateManager(
        session_id=sid, task_id="seed", user_input="在任务目录创建 note.txt")
    sm.set_todos([{
        "id": "1",
        "title": "把 note.txt 的 hi 改成 hello resume",
        "action": "file_operations",
        "params": {"operation": "edit", "files": [
            {"path": "note.txt", "old_string": "hi", "new_string": "hello resume"}]},
    }])
    sm.note_failure("1/1 个待办失败：任务未按要求完成")
    assert await sm.save_state(), "断点播种失败"
    print("断点已播种: failed_error + 1 条 pending 待办(edit files[])")

    # ---- 第2轮：只发「继续」 ----
    ev2 = await run_turn("继续", "E2E-断点-轮2")
    types2 = [e for e, _ in ev2]
    print("轮2 事件:", types2)
    todos_ev = [d for e, d in ev2 if e == "todos"]
    if todos_ev:
        print("轮2 todos 事件:", todos_ev[0][:400])

    failures = []
    content = target.read_text(encoding="utf-8")
    print("note.txt 内容:", repr(content))
    if "hello resume" not in content:
        failures.append("edit files[] 批量未执行（文件内容未变）")
    if "resumed" not in types2:
        failures.append("轮2 没有收到 resumed 断点恢复事件")

    sm2 = ExecutionStateManager(session_id=sid, task_id="x", user_input="")
    if await sm2.load_state():
        failures.append("成功收尾后断点状态未清除")
    if sm2.failed_error:
        failures.append(f"failed_error 未消费: {sm2.failed_error}")

    async with AsyncSessionLocal() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM conversation_messages "
            "WHERE session_id=:s AND content LIKE '%缺少 path%'"),
            {"s": sid})).scalar()
    print("会话中'缺少 path'消息数:", n)
    if n:
        failures.append(f"仍出现'缺少 path 参数'错误 x{n}")

    # 恢复的必须是播种待办，而不是字面量「继续」
    async with AsyncSessionLocal() as db:
        bad = (await db.execute(text(
            "SELECT count(*) FROM conversation_messages "
            "WHERE session_id=:s AND role='assistant' AND content LIKE '%待办%继续%'"),
            {"s": sid})).scalar()
    print("字面量待办「继续」迹象:", bad)

    # complete 后客户端断开不得把任务误标"任务被取消"（首跑 e2e 实测会）
    async with AsyncSessionLocal() as db:
        trow = (await db.execute(text(
            "SELECT status, error FROM tasks WHERE task_id=:t"), {"t": sid})).first()
    print("任务状态:", trow)
    if not trow or trow[0] != "completed":
        failures.append(f"任务状态应为 completed, 实际 {trow}")

    if failures:
        print("\nRESULT: FAIL")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("\nRESULT: PASS — resumed 事件、files[] 批量已执行、断点已消费、无缺参错误")


asyncio.run(main())
