"""生产实测：move 搬空自动删源目录 / delete 删光自动清父目录。"""
import asyncio, sys, time
sys.path.insert(0, "/www/wwwroot/aiagent/AiAgent_backend_langgraph")
from app.agent.skills.file_operations.skill import skill as S

async def main():
    r = await S.execute(operation="create", path=f"rmdir_smoke_{int(time.time())}",
                        content="placeholder.txt::x", session_id="rmdir_smoke")
    assert r.success, r.error
    name = r.data["project_name"]
    root = S._tasks_dir / name
    (root / "old").mkdir()
    (root / "old" / "a.txt").write_text("A")
    (root / "old" / "b.txt").write_text("B")

    r1 = await S.execute(operation="move", path="old/a.txt", dest="docs/a.txt",
                         task_path=name, session_id="rmdir_smoke")
    print("move1:", r1.success, "| old exists:", (root / "old").exists())
    r2 = await S.execute(operation="move", path="old/b.txt", dest="docs/b.txt",
                         task_path=name, session_id="rmdir_smoke")
    print("move2:", r2.success, "| note:", r2.data.get("note"), "| old exists:", (root / "old").exists())

    (root / "t2").mkdir()
    (root / "t2" / "f.txt").write_text("F")
    r3 = await S.execute(operation="delete", path="t2/f.txt",
                         task_path=name, session_id="rmdir_smoke")
    print("delete:", r3.success, "| t2 exists:", (root / "t2").exists())
    print("PASS" if (not (root / "old").exists() and not (root / "t2").exists()
                     and (root / "docs" / "b.txt").exists()) else "FAIL")
    import shutil
    shutil.rmtree(root, ignore_errors=True)

asyncio.run(main())
