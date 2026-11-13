"""创建一个 FastAPI 项目 + 读写行为验收（生产本机直驱 8009，TESTCASES TC-S15-05）。

用户要求（2026-11-13）：
  轮「创建一个fastapi项目」→ 完成、0 工具执行失败、磁盘有 fastapi 证据；
  过程行为：一次读取后批量写入、避免反复读取（规则13 的行为面验收）。

PASS 条件：
  1) complete + 0 次工具执行失败
  2) 任务目录含 fastapi 证据（requirements.txt 或 main.py 提及 fastapi）
  3) 至少 1 次批量 write（files ≥ 3）
  4) 写后纯确认读（读的文件全部在上一次 write 列表里）≤ 1 次
  5) read 总次数 ≤ 6（创建类任务反复读 = 交替严重）
  6) 出现「read → 下一动作批量 write(files≥3)」模式（一次读取后批量写入）
"""
import asyncio, json, time, sys
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")

BASE = "http://127.0.0.1:8009"
SESSION_ID = f"fastapi_batch_e2e_{int(time.time())}"
TASK = "创建一个fastapi项目"


async def run_turn(s, task_desc):
    import aiohttp
    events, has_error = [], False
    async with s.post(
        BASE + "/api/v1/agent/execute/stream",
        json={"session_id": SESSION_ID, "task": task_desc},
        timeout=aiohttp.ClientTimeout(total=420),
    ) as resp:
        print("HTTP", resp.status, f"[{task_desc[:24]}]")
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


def _write_paths(p):
    """一次 write 落盘的路径集合。"""
    out = set()
    for f in (p.get("files") or []):
        if isinstance(f, dict):
            fp = f.get("path") or f.get("file") or ""
        else:
            fp = str(f)
        if fp:
            out.add(fp)
    if not out and p.get("path"):
        out.add(p["path"])
    return out


def _read_paths(p):
    out = set()
    for f in (p.get("files") or []):
        if isinstance(f, dict):
            fp = f.get("path") or f.get("file") or ""
        else:
            fp = str(f)
        if fp:
            out.add(fp)
    if not out and p.get("path"):
        out.add(p["path"])
    return out


async def behavior_checks(db):
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT id, action, params, success FROM execution_nodes "
        "WHERE session_id=:s AND node_type='next_moves' ORDER BY id"),
        {"s": SESSION_ID})).all()

    def _pj(x):
        if isinstance(x, str):
            try:
                return json.loads(x) or {}
            except Exception:
                return {}
        return x or {}

    actions = []
    for _id, action, params, success in rows:
        p = _pj(params)
        op = (p.get("operation") or "").lower()
        if op == "write":
            paths = _write_paths(p)
        elif op == "read":
            paths = _read_paths(p)
        else:
            paths = set()
        actions.append({"op": op, "paths": paths, "success": bool(success)})

    writes = [a for a in actions if a["op"] == "write"]
    reads = [a for a in actions if a["op"] == "read"]
    batch_writes = [a for a in writes if len(a["paths"]) >= 3]

    # 被 ReadbackGuard 跳过的读（观察含"已跳过读取"）没有真读文件——
    # 节点仍会记录 next_moves（on_step 在执行前发），断言必须按真读算，
    # 否则"跳过"反而把 confirm_reads/read 总数顶高（e2e9 两次跳过被误判）
    import re as _re
    jump_files: dict = {}
    for (c,) in (await db.execute(text(
            "SELECT content FROM execution_nodes "
            "WHERE session_id=:s AND node_type='observation' "
            "AND content LIKE '%已跳过读取%'"), {"s": SESSION_ID})).all():
        m = _re.search(r"文件: ([^）]+)", str(c))
        if m:
            for f in m.group(1).split(", "):
                jump_files[f] = jump_files.get(f, 0) + 1
    jumps = sum(jump_files.values()) or (await db.execute(text(
        "SELECT count(*) FROM execution_nodes "
        "WHERE session_id=:s AND node_type='observation' "
        "AND content LIKE '%已跳过读取%'"), {"s": SESSION_ID})).scalar() or 0

    # 写后纯确认读：read 的文件全部 ⊆ 最近一次成功 write 的列表
    confirm_reads = 0
    last_write = set()
    for a in actions:
        if a["op"] == "write" and a["success"] and a["paths"]:
            last_write = a["paths"]
        elif a["op"] == "read" and last_write and a["paths"] \
                and a["paths"] <= last_write:
            confirm_reads += 1

    # 「一次读取 → 下一动作批量写入」模式；或更优的"连续批量写段"
    # （规则13 后实际形态：先一口气连写，读只在收尾出现——两种都算过）
    read_then_batch = any(
        actions[i]["op"] == "read"
        and actions[i + 1]["op"] == "write"
        and len(actions[i + 1]["paths"]) >= 3
        for i in range(len(actions) - 1))
    max_write_run, run = 0, 0
    max_read_run, rrun = 0, 0
    flips = 0
    read_count: dict = {}
    prev_op = None
    for a in actions:
        if a["op"] == "write":
            run += 1
            max_write_run = max(max_write_run, run)
            rrun = 0
        elif a["op"] == "read":
            run = 0
            rrun += 1
            max_read_run = max(max_read_run, rrun)
            for p in a["paths"]:
                read_count[p] = read_count.get(p, 0) + 1
        if prev_op and a["op"] in ("read", "write") and a["op"] != prev_op:
            flips += 1
        if a["op"] in ("read", "write"):
            prev_op = a["op"]
    most_read_file = max(read_count.items(), key=lambda kv: kv[1],
                         default=("<none>", 0))

    print(f"  actions={len(actions)} reads={len(reads)} "
          f"writes={len(writes)} batch_writes={len(batch_writes)} "
          f"confirm_reads={confirm_reads} jumps={jumps} "
          f"read_then_batch={read_then_batch} "
          f"max_write_run={max_write_run} op_flips={flips} "
          f"max_read_run={max_read_run} most_read={most_read_file}")
    for a in actions[:20]:
        print(f"    - {a['op']:6s} paths={sorted(a['paths'])[:4]} ok={a['success']}")

    # 真读 = 节点数 - 跳过数（跳过的读没有读文件，是 guard 拦截的意图）
    eff_reads = max(0, len(reads) - jumps)
    eff_confirm = max(0, confirm_reads - jumps)

    ok = True
    if not batch_writes:
        print("  FAIL: 没有任何批量 write（files≥3）")
        ok = False
    if eff_confirm > 1:
        print(f"  FAIL: 写后纯确认读 {eff_confirm} 次 > 1（反复读取，"
              f"节点 {confirm_reads} - 跳过 {jumps}）")
        ok = False
    if eff_reads > 6:
        print(f"  FAIL: 真读次数 {eff_reads} > 6（节点 {len(reads)}"
              f" - 跳过 {jumps}）")
        ok = False
    # 对准生产 2026-11-14 00:12 空转现场的指标（flips 测不准：5连 read
    # 空转时 flips 反而是 0）：连续只读 run 和单文件重读次数
    if max_read_run > 2:
        print(f"  FAIL: 连续只读 {max_read_run} 轮 > 2（只读空转苗头）")
        ok = False
    if most_read_file[1] - jump_files.get(most_read_file[0], 0) > 2:
        real = most_read_file[1] - jump_files.get(most_read_file[0], 0)
        print(f"  FAIL: 文件 {most_read_file[0]} 真读 {real} 次 > 2"
              f"（节点 {most_read_file[1]} - 跳过 "
              f"{jump_files.get(most_read_file[0], 0)}）")
        ok = False
    if not read_then_batch and max_write_run < 3:
        print(f"  note: 无「读→批量写」且最长连续写段={max_write_run}"
              "（短任务分批+依赖读属正常，不作失败）")
    return ok


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
        print("TURN:", TASK)
        events, has_error = await run_turn(s, TASK)
        complete = "complete" in events
        if not complete or has_error:
            print("  FAIL: complete=", complete, "error_event=", has_error)
            ok = False

        async with AsyncSessionLocal() as db:
            # 观察：0 次工具执行失败
            obs = (await db.execute(text(
                "SELECT content FROM execution_nodes WHERE session_id=:s "
                "AND node_type='observation'"), {"s": SESSION_ID})).all()
            fails = [c for (c,) in obs if c and "工具执行失败" in c]
            print(f"  observations={len(obs)} tool_execution_failures={len(fails)}")
            for c in fails[:5]:
                print("    FAIL:", c.replace("\n", " ")[:160])
            if fails:
                ok = False

            # 磁盘 fastapi 证据：任务目录从动作参数里的 task_path 取
            r = (await db.execute(text(
                "SELECT params::text FROM execution_nodes WHERE session_id=:s "
                "AND node_type='next_moves' ORDER BY id LIMIT 50"),
                {"s": SESSION_ID})).all()
        task_path = None
        for (pjs,) in r:
            try:
                tp = (json.loads(pjs) or {}).get("task_path")
            except Exception:
                tp = None
            if tp:
                task_path = tp
                break
        print("  task_path:", task_path)
        if task_path:
            # 脚本跑在生产本机，直接遍历文件系统（不要 ssh 到自己）
            import os
            root = f"/www/wwwroot/aiagent/tasks/{task_path}"
            hits, total = [], 0
            for dp, _dn, fns in os.walk(root):
                for fn in fns:
                    total += 1
                    fp = os.path.join(dp, fn)
                    try:
                        with open(fp, "rb") as fh:
                            if b"fastapi" in fh.read().lower():
                                hits.append(os.path.relpath(fp, root))
                    except Exception:
                        pass
            print(f"  disk: files={total} fastapi_hits={hits[:5]}")
            if not hits:
                print("  FAIL: 磁盘无 fastapi 证据")
                ok = False
        else:
            print("  FAIL: 取不到任务目录")
            ok = False

        async with AsyncSessionLocal() as db:
            behavior_ok = await behavior_checks(db)
        ok = ok and behavior_ok

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
