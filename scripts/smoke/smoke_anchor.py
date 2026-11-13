"""验收：新会话文件任务开局锚定任务目录（任务86根因修复）。
断言：① 首轮观察不泄漏 tasks 根/其他任务目录 ② 无"读不存在文件"连败
③ session_contexts 写入 task_path ④ journal 有锚定日志。"""
import asyncio, json, sys, time
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")
import aiohttp

BASE = "http://127.0.0.1:8009"
TASK = "创建一个Flask博客项目，包含应用工厂、配置、入口文件，先把项目框架搭好"
SESSION = "session_smoke_anchor_1"


async def main():
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        uid = (await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar()
    from app.core.security import create_access_token
    token = create_access_token(str(uid))
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}

    events, t0 = [], time.time()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=160)) as s:
        async with s.post(f"{BASE}/api/v1/agent/execute/stream",
                          json={"task": TASK, "session_id": SESSION},
                          headers=headers) as resp:
            print("HTTP", resp.status)
            buf = ""
            async for chunk in resp.content.iter_any():
                if time.time() - t0 > 150:
                    print("TIMEOUT"); break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    etype = None; data = ""
                    for ln in block.splitlines():
                        if ln.startswith("event:"): etype = ln[6:].strip()
                        elif ln.startswith("data:"): data += ln[5:].strip()
                    if etype:
                        events.append((etype, data))
                        if etype in ("error", "complete"):
                            print(f"{int(time.time()-t0):>3}s {etype}: {data[:260]}")
                            if etype == "complete":
                                break
                if events and events[-1][0] == "complete":
                    break
    # 观察泄漏/读失败检查
    leak, readfail = [], []
    for et, d in events:
        if et != "observation":
            continue
        try:
            c = json.loads(d).get("content", "")
        except Exception:
            continue
        if "任务目录列表如下" in c and ("auto_project_" in c or "session_" in c):
            leak.append(c[:150])
        if "文件不存在" in c:
            readfail.append(c[:150])
    print("LEAK_OBS:", len(leak))
    print("READ_NOTFOUND_OBS:", len(readfail))
    for x in (leak + readfail)[:4]:
        print("  !", x.replace("\n", " "))

    async with AsyncSessionLocal() as db:
        r = (await db.execute(text(
            "SELECT context_value::text FROM session_contexts WHERE session_id=:s AND context_key='task_path'"),
            {"s": SESSION})).scalar()
        print("PERSISTED_task_path:", r)
        r = (await db.execute(text(
            "SELECT node_type, action, COALESCE(left(content,150),'') FROM execution_nodes "
            "WHERE session_id=:s ORDER BY id ASC LIMIT 10"), {"s": SESSION})).all()
        for n in r:
            print("NODE", n[0], n[1], "|", (n[2] or "").replace("\n", " ")[:150])

asyncio.run(main())
