"""move/归类任务端到端验收（生产本机直驱 8009）：
轮1 造根目录文件；轮2 下达 task82 同款迁移需求。
断言：backend/ 有文件 + 根目录原文件消失（task82 的失败点），待办状态与磁盘一致。
"""
import asyncio, json, time, sys
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")

BASE = "http://127.0.0.1:8009"
SESSION_ID = f"move_e2e_{int(time.time())}"


async def run_turn(s, task_desc):
    events = []
    import aiohttp
    async with s.post(
        BASE + "/api/v1/agent/execute/stream",
        json={"session_id": SESSION_ID, "task": task_desc},
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
                    buf = ""
    print(f"turn done [{task_desc[:16]}...] events={len(events)} tail={events[-3:]}")
    return events


async def main():
    import aiohttp
    from app.core.security import create_access_token
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        uid = (await db.execute(text("SELECT id FROM users ORDER BY id LIMIT 1"))).scalar()
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}

    async with aiohttp.ClientSession(headers=headers) as s:
        await run_turn(s, "在任务目录根下创建三个文件：app.py（内容 print('app')）、"
                          "config.py（内容 DEBUG = True）、models.py（内容 class Model: pass）")
        await asyncio.sleep(3)
        await run_turn(s, "把根目录的后端文件 app.py、config.py、models.py 统一移动到 backend "
                          "目录里管理，移动后根目录不再保留这些文件")

    async with AsyncSessionLocal() as db:
        tp = (await db.execute(text(
            "SELECT context_value FROM session_contexts WHERE session_id=:s AND context_key='task_path'"),
            {"s": SESSION_ID})).scalar()
        print("task_path =", tp)
        if not tp:
            print("FAIL: no task_path"); return

        from app.agent.skills.file_operations.skill import get_tasks_dir
        root = get_tasks_dir() / json.loads(tp) if tp.startswith('"') else get_tasks_dir() / tp
        print("root =", root)
        root_files = sorted(p.name for p in root.iterdir())
        print("root entries =", root_files)
        backend = root / "backend"
        be_files = sorted(p.name for p in backend.iterdir()) if backend.exists() else []
        print("backend files =", be_files)

        # 执行动作取证：本轮用了哪些 file_operations operation
        rows = (await db.execute(text(
            "SELECT action, result::text FROM execution_nodes WHERE session_id=:s "
            "AND action IS NOT NULL ORDER BY id"), {"s": SESSION_ID})).all()
        ops = []
        for a, r in rows:
            if a == "file_operations":
                try:
                    ops.append(json.loads(r).get("operation"))
                except Exception:
                    ops.append("?")
        print("file_operations ops =", ops)

        # 待办状态
        wm = (await db.execute(text(
            "SELECT memory_value FROM working_memory WHERE session_id=:s AND memory_key='execution_state'"),
            {"s": SESSION_ID})).scalar()
        todos = json.loads(wm).get("todos", []) if wm else []
        print("todos =", [(t.get("status"), (t.get("content") or "")[:40]) for t in todos])

    moved_ok = backend.exists() and all((root / f).exists() for f in ["app.py", "config.py", "models.py"]) is False
    root_clean = not any((root / f).exists() for f in ["app.py", "config.py", "models.py"])
    be_ok = all((backend / f).exists() for f in ["app.py", "config.py", "models.py"])
    todos_ok = all(t.get("status") == "completed" for t in todos) if todos else False
    # 一致性：待办全 completed 必须以磁盘为证
    honest = (not todos_ok) or (root_clean and be_ok)
    print(f"RESULT: root_clean={root_clean} backend_ok={be_ok} "
          f"todos_all_completed={todos_ok} honest={honest}")
    print("PASS" if (root_clean and be_ok and honest) else "FAIL")


asyncio.run(main())
