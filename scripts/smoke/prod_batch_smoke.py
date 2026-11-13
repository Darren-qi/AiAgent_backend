"""生产验收：批量并发创建 files 数组是否被真实使用 + 无 format 崩溃。"""
import asyncio, json, sys, time
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")
import aiohttp
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8009"
TASK = "创建一个Flask博客项目，包含应用工厂、配置、入口文件、依赖清单，先把项目骨架搭好"
SESSION = "session_batch_smoke_1"


async def main():
    async with AsyncSessionLocal() as db:
        uid = (await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar()
    token = create_access_token(str(uid))
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    t0 = time.time()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=200)) as s:
        async with s.post(f"{BASE}/api/v1/agent/execute/stream",
                          json={"task": TASK, "session_id": SESSION},
                          headers=headers) as resp:
            print("HTTP", resp.status)
            buf = ""
            async for chunk in resp.content.iter_any():
                if time.time() - t0 > 190:
                    print("TIMEOUT"); break
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    etype = None; data = ""
                    for ln in block.splitlines():
                        if ln.startswith("event:"): etype = ln[6:].strip()
                        elif ln.startswith("data:"): data += ln[5:].strip()
                    if etype in ("error", "complete"):
                        print(f"{int(time.time()-t0):>3}s {etype}: {data[:200]}")
                        if etype == "complete":
                            buf = ""
                            break

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT node_type, action, COALESCE(content,'') FROM execution_nodes "
            "WHERE session_id=:s ORDER BY id ASC"), {"s": SESSION})).all()
    actions, batch_nodes = [], []
    for nt, act, c in rows:
        if nt == "planning":
            actions.append(act)
            if '"files"' in c:
                batch_nodes.append(c[:160])
    print("TOTAL_NODES:", len(rows), "| PLANNING_ROUNDS:", len(actions))
    print("ACTIONS:", actions)
    print("BATCH_WRITE_NODES:", len(batch_nodes))
    for b in batch_nodes[:3]:
        print("  B:", b.replace("\n", " ")[:160])
    keyerr = [c for _, _, c in rows if "KeyError" in (c or "")]
    print("KEYERROR_NODES:", len(keyerr))

asyncio.run(main())
