"""端到端验证：流式跑一个小任务 → 检查 assistant 是否落库 → get-session 能否读回。"""
import asyncio
import json

BASE = "http://127.0.0.1:8099"
SESSION_ID = f"e2e_asst_{int(asyncio.get_event_loop().time() * 1000)}"


async def main():
    from app.core.security import create_access_token
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("SELECT id, username FROM users LIMIT 1"))).all()
    token = create_access_token(str(rows[0][0]))
    print("user:", rows[0], "session:", SESSION_ID)

    import aiohttp  # noqa: F401 - venv 内通常有
    payload = {
        "session_id": SESSION_ID,
        "task": "在任务目录创建 hello_e2e.txt，内容为 hi",
        "title": "E2E assistant 持久化验证",
    }
    events = []
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{BASE}/api/v1/agent/execute/stream",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=300),
        ) as resp:
            print("HTTP", resp.status)
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
                        if etype in ("complete", "error", "stopped"):
                            print("terminal event:", etype)
                            break
                    else:
                        continue
                if events and events[-1] in ("complete", "error", "stopped"):
                    break
    print("event types:", events)

    await asyncio.sleep(3)  # 给服务端异步落库留时间
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT role, length(content), left(content,60) FROM conversation_messages "
            "WHERE session_id=:s ORDER BY sequence"), {"s": SESSION_ID})).all()
    print("conversation_messages:")
    for r in rows:
        print("  ", r)

    from app.api.v1.endpoints.agent import get_session
    res = await get_session(session_id=SESSION_ID, user=None)
    d = res["data"]
    print("get-session: code=", res["code"],
          "msgs=", [(m["type"], len(m.get("content") or "")) for m in d["messages"]],
          "tree=", len(d["file_tree"]), "task_path=", d["task_path"])
    print("RESULT:", "PASS" if any(m["type"] == "assistant" for m in d["messages"]) else "FAIL")


asyncio.run(main())
