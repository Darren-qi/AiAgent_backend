"""后端修复冒烟：裸名 extensions.py 提问 → 模型应凭文件清单一次读对 app/extensions.py。"""
import asyncio, json, sys, time
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")

BASE = "http://127.0.0.1:8009"
TASK = "看一下 extensions.py 里定义了什么，用一句话告诉我结论"

async def main():
    import aiohttp
    from app.core.security import create_access_token
    from sqlalchemy import text as sqltext
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        uid = (await db.execute(sqltext("SELECT id FROM users ORDER BY id LIMIT 1"))).scalar()
    token = create_access_token(str(uid))
    headers = {"Authorization": f"Bearer {token}"}
    events = []
    t0 = time.time()
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.post(
            BASE + "/api/v1/agent/execute/stream",
            json={"session_id": "session_smoke_pathfix_1", "task": TASK},
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            print("HTTP", resp.status)
            buf = ""
            async for chunk in resp.content.iter_any():
                if time.time() - t0 > 300: break
                buf += chunk.decode("utf-8", "replace")
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    etype, data = "", ""
                    for ln in block.split("\n"):
                        if ln.startswith("event:"): etype = ln[6:].strip()
                        elif ln.startswith("data:"): data = ln[5:].strip()
                    if etype:
                        events.append(etype)
                        if etype in ("next_moves", "error", "complete"):
                            detail = data[:160]
                            try:
                                d = json.loads(data)
                                if etype == "next_moves":
                                    p = d.get("params") or {}
                                    detail = f"op={p.get('operation')} path={p.get('path')}"
                            except Exception:
                                pass
                            print(f"{int(time.time()-t0):>3}s {etype}: {detail}")
                    if etype in ("complete", "error", "stopped"):
                        buf = ""
    # 取证：本次会话的执行节点里 read 失败次数（错误路径）vs 成功读取
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(sqltext(
            "SELECT node_type, action, success, params::text, LEFT(COALESCE(content,''),60) "
            "FROM execution_nodes WHERE session_id='session_smoke_pathfix_1' ORDER BY id"))).all()
    print("---- nodes ----")
    for r in rows:
        print(r)
    bad = [r for r in rows if r[1] == "file_operations" and r[2] is False and "文件不存在" in (r[4] or "")]
    print("READ_NOTFOUND:", len(bad))
    print("SMOKE_DONE complete=", "complete" in events)

asyncio.run(main())
