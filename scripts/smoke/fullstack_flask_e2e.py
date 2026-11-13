"""两阶段真实场景端到端验收（生产本机直驱 8009，TESTCASES TC-S16-01）。

用户常用手动场景：
  轮1「创建一个Flask博客项目」→ 断言中间流程不报错（无工具执行失败）
  轮2「将前端改为vue3框架，后端改为FastAPI框架，并将现有文件归类到前后端目录」
    → 断言正确归类且根目录只剩前后端两个子目录
PASS 条件：两轮 complete、全程 0 次工具执行失败、根目录恰好2个子目录、
前端含 vue3 证据、后端含 fastapi 证据。
"""
import asyncio, json, time, sys
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")

BASE = "http://127.0.0.1:8009"
SESSION_ID = f"fullstack_e2e_{int(time.time())}"

TURN1 = "创建一个Flask博客项目"
TURN2 = "将前端改为vue3框架，后端改为FastAPI框架，并将现有文件归类到前后端目录"


async def run_turn(s, task_desc):
    """发一轮任务，返回 (events尾部, 是否有error事件)。"""
    import aiohttp
    events, has_error = [], False
    async with s.post(
        BASE + "/api/v1/agent/execute/stream",
        json={"session_id": SESSION_ID, "task": task_desc},
        timeout=aiohttp.ClientTimeout(total=420),
    ) as resp:
        print("HTTP", resp.status, f"[{task_desc[:18]}...]")
        buf = ""
        async for chunk in resp.content.iter_any():
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                etype = ""
                for ln in block.split("\n"):
                    if ln.startswith("event:"):
                        etype = ln[6:].strip()
                if etype:
                    events.append(etype)
                    if etype == "error":
                        has_error = True
                        for ln in block.split("\n"):
                            if ln.startswith("data:"):
                                print("  ERROR-EVENT:", ln[5:].strip()[:300])
                if etype in ("complete", "error", "stopped"):
                    buf = ""
    print(f"  turn done events={len(events)} tail={events[-3:]} error_event={has_error}")
    return events, has_error


async def db_checks(db, tool_fail_max: int):
    """查本会话工具执行失败次数（观察里含'工具执行失败'）。"""
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT content FROM execution_nodes WHERE session_id=:s "
        "AND node_type='observation'"), {"s": SESSION_ID})).all()
    tool_fails = [c for (c,) in rows if c and "工具执行失败" in c]
    print(f"  observations={len(rows)} tool_execution_failures={len(tool_fails)}")
    for c in tool_fails[:5]:
        print("    FAIL:", c.replace("\n", " ")[:160])
    return len(tool_fails) <= tool_fail_max


async def main():
    import aiohttp
    from app.core.security import create_access_token
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        uid = (await db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1"))).scalar()
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}

    ok = True
    async with aiohttp.ClientSession(headers=headers) as s:
        # ── 轮1：创建 Flask 博客，中间流程不报错 ──
        print("TURN1:", TURN1)
        ev1, err1 = await run_turn(s, TURN1)
        async with AsyncSessionLocal() as db:
            t1_ok = await db_checks(db, tool_fail_max=0)
        if err1 or "complete" not in ev1:
            ok = False
            print("  TURN1 FAIL: error_event/无complete")

        # ── 轮2：重构前后端 + 归类 ──
        print("TURN2:", TURN2)
        ev2, err2 = await run_turn(s, TURN2)
        async with AsyncSessionLocal() as db:
            t2_ok = await db_checks(db, tool_fail_max=0)
            tp = (await db.execute(text(
                "SELECT context_value FROM session_contexts WHERE session_id=:s "
                "AND context_key='task_path'"), {"s": SESSION_ID})).scalar()
        if err2 or "complete" not in ev2:
            ok = False
            print("  TURN2 FAIL: error_event/无complete")

        # ── 磁盘断言 ──
        from app.agent.skills.file_operations.skill import get_tasks_dir
        root = get_tasks_dir() / json.loads(tp) if tp and tp.startswith('"') else get_tasks_dir() / (tp or "")
        print("root =", root)
        entries = sorted(p for p in root.iterdir()) if root.exists() else []
        names = [p.name for p in entries]
        print("root entries =", names)
        only_two = len(entries) == 2 and all(p.is_dir() for p in entries)
        if not only_two:
            ok = False
            print("  FAIL: 根目录不是恰好两个子目录")

        def has_text(d, needle):
            if not d or not d.exists():
                return False
            for p in d.rglob("*"):
                if p.is_file() and p.suffix in (".py", ".txt", ".json", ".js", ".ts", ".vue"):
                    try:
                        if needle in p.read_text(errors="ignore"):
                            return True
                    except Exception:
                        pass
            return False

        # 识别哪个是前端/后端（不写死目录名）
        fe = be = None
        for d in entries:
            if not d.is_dir():
                continue
            if has_text(d, "vue"):
                fe = d
            if has_text(d, "fastapi"):
                be = d
        print(f"frontend_dir={fe.name if fe else None} backend_dir={be.name if be else None}")
        if not fe or not be:
            ok = False
            print("  FAIL: 缺 vue3 或 fastapi 证据")

        # 前端骨架至少一个 .vue 文件
        vue_files = list(fe.rglob("*.vue")) if fe else []
        print(f"  .vue files = {len(vue_files)}")
        if not vue_files:
            ok = False
            print("  FAIL: 前端没有 .vue 文件")

    final = ok and t1_ok and t2_ok
    print(f"RESULT: turn1_clean={t1_ok} turn2_clean={t2_ok} disk_ok={ok}")
    print("PASS" if final else "FAIL")


asyncio.run(main())
