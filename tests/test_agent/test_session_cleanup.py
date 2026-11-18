"""会话级联清理（子表 + 磁盘任务目录）测试 —— 2026-11-18。

覆盖：目录名解析（context_value / absolute_path）、路径安全（只准删 tasks/ 直下子目录）、
动态子表发现（不含 sessions）、cleanup_session 编排（收集→删子表→删父→删目录）。
不连真实 DB：用 FakeDB 记录执行过的语句。
"""

import pytest

from app.agent import session_cleanup as sc


class FakeResult:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """记录执行语句；按语句内容返回不同结果。"""

    def __init__(self, tables=(), ctx_values=(), abs_paths=(), other_ctx_values=()):
        self.tables = list(tables)
        self.ctx_values = list(ctx_values)
        self.abs_paths = list(abs_paths)
        self.other_ctx_values = list(other_ctx_values)
        self.executed = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.executed.append((s, params))
        if "information_schema" in s:
            return FakeResult(rows=[(t,) for t in self.tables])
        if "session_id !=" in s or "session_id!=" in s:
            return FakeResult(rows=list(self.other_ctx_values))
        if "context_value" in s:
            return FakeResult(rows=list(self.ctx_values))
        if "absolute_path" in s:
            return FakeResult(rows=list(self.abs_paths))
        return FakeResult(rowcount=1)

    async def commit(self):
        self.commits += 1

    def deletes(self):
        return [(s, p) for s, p in self.executed if s.strip().lower().startswith("delete")]


TABLES = ["action_journal", "conversation_messages", "execution_nodes",
          "session_contexts", "session_files", "sessions", "tasks", "working_memory"]


@pytest.fixture
def tasks_root(tmp_path, monkeypatch):
    root = tmp_path / "tasks"
    root.mkdir()
    monkeypatch.setattr(sc, "tasks_base_dir", lambda: root)
    return root


class TestDirNameParsing:
    def test_context_value_json_string(self):
        assert sc._dir_names_from_context_values(['"auto_project_123"']) == {"auto_project_123"}

    def test_context_value_plain_and_none(self):
        assert sc._dir_names_from_context_values(["tasks/calculator_9", None]) == {"calculator_9"}

    def test_absolute_path_segment(self):
        paths = [
            "/www/wwwroot/aiagent/tasks/auto_project_1/x.py",
            "/old/backend/tasks/calculator_2/y.py",
            "/no/tasks/here.py",
            None,
        ]
        assert sc._dir_names_from_absolute_paths(paths) == {"auto_project_1", "calculator_2"}

    def test_absolute_path_rejects_traversal(self):
        assert sc._dir_names_from_absolute_paths(["/a/tasks/../etc/passwd"]) == set()


class TestPathSafety:
    def test_only_direct_child_of_tasks(self, tasks_root):
        (tasks_root / "good").mkdir()
        outside = tasks_root.parent / "victim"
        outside.mkdir()
        assert sc.safe_task_dir(tasks_root / "good") is True
        assert sc.safe_task_dir(tasks_root / ".." / "victim") is False
        assert sc.safe_task_dir(tasks_root / "a" / "b") is False

    def test_rejects_bad_names(self, tasks_root):
        assert sc.safe_task_dir(tasks_root / "..") is False
        assert sc.safe_task_dir(tasks_root / ".") is False
        assert sc.safe_task_dir(tasks_root / "x/y") is False

    def test_symlink_escape_not_removed(self, tasks_root, tmp_path):
        """symlink 指到 tasks 外面 → 不得顺手把目标删了。"""
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "keep.txt").write_text("x")
        link = tasks_root / "evil"
        link.symlink_to(outside, target_is_directory=True)
        removed = sc.remove_task_dirs(["evil"])
        assert removed == []
        assert (outside / "keep.txt").exists()

    def test_remove_only_named_dirs(self, tasks_root):
        (tasks_root / "mine").mkdir()
        (tasks_root / "mine" / "a.txt").write_text("a")
        (tasks_root / "others").mkdir()
        (tasks_root / "others" / "b.txt").write_text("b")
        removed = sc.remove_task_dirs(["mine"])
        assert len(removed) == 1
        assert not (tasks_root / "mine").exists()
        assert (tasks_root / "others" / "b.txt").exists()

    def test_missing_dir_is_noop(self, tasks_root):
        assert sc.remove_task_dirs(["nope"]) == []


class TestChildRowDeletion:
    @pytest.mark.asyncio
    async def test_all_session_tables_except_parent(self):
        db = FakeDB(tables=TABLES)
        result = await sc.delete_session_child_rows(db, "session_1")
        deleted_tables = [s.split("public.")[1].split(" ")[0]
                          for s, _ in db.deletes()]
        assert "sessions" not in deleted_tables, "父表必须由调用方决定何时删"
        assert sorted(deleted_tables) == sorted(set(TABLES) - {"sessions"})
        assert result["session_files"] == 1

    @pytest.mark.asyncio
    async def test_weird_table_name_skipped(self):
        # information_schema 里混进非法表名（分号/大写/带引号）→ 不得拼进 SQL
        db = FakeDB(tables=["tasks", "bad;name", "BadName", "ok_table"])
        await sc.delete_session_child_rows(db, "session_1")
        stmts = [s for s, _ in db.deletes()]
        assert all("bad" not in s and "BadName" not in s for s in stmts)
        assert any("public.tasks" in s for s in stmts)
        assert any("public.ok_table" in s for s in stmts)


class TestCleanupSession:
    @pytest.mark.asyncio
    async def test_end_to_end(self, tasks_root):
        (tasks_root / "auto_project_1").mkdir()
        (tasks_root / "auto_project_1" / "main.py").write_text("print()")
        db = FakeDB(
            tables=TABLES,
            ctx_values=['"auto_project_1"'],
            abs_paths=["/www/tasks/auto_project_1/main.py"],
        )
        out = await sc.cleanup_session(db, "session_1", delete_parent=True)

        assert out["parent"] is True
        assert out["tables"]["session_files"] == 1
        assert len(out["dirs"]) == 1
        assert not (tasks_root / "auto_project_1").exists()
        assert db.commits == 1
        # 父表删除必须排在子表之后
        stmts = [s for s, _ in db.deletes()]
        assert any("delete from public.sessions" in s for s in stmts)

    @pytest.mark.asyncio
    async def test_keep_parent_when_not_asked(self, tasks_root):
        db = FakeDB(tables=TABLES, ctx_values=[])
        out = await sc.cleanup_session(db, "session_1", delete_parent=False)
        assert out["parent"] is False
        assert all("delete from public.sessions" not in str(s) for s, _ in db.deletes())

    @pytest.mark.asyncio
    async def test_collects_dirs_before_deleting_rows(self, tasks_root):
        """目录映射在子表里：必须先收集、后删行，否则永远删不掉目录。"""
        (tasks_root / "auto_project_9").mkdir()
        db = FakeDB(tables=TABLES, ctx_values=['"auto_project_9"'])
        out = await sc.cleanup_session(db, "session_9")
        assert out["dirs"], "先读后删，目录映射不能丢"
        assert not (tasks_root / "auto_project_9").exists()

    @pytest.mark.asyncio
    async def test_shared_dir_of_other_session_kept(self, tasks_root):
        """别的会话还在用的目录：删会话绝不能把它删掉。"""
        (tasks_root / "shared_project").mkdir()
        (tasks_root / "shared_project" / "a.py").write_text("a")
        (tasks_root / "mine_only").mkdir()
        db = FakeDB(
            tables=TABLES,
            ctx_values=['"shared_project"', '"mine_only"'],
            other_ctx_values=['"shared_project"'],
        )
        out = await sc.cleanup_session(db, "session_1")
        assert out["dirs"] == [str(tasks_root / "mine_only")]
        assert (tasks_root / "shared_project" / "a.py").exists(), "共享目录必须保留"
        assert not (tasks_root / "mine_only").exists()
