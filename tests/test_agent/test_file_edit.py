"""file_operations edit（局部替换）专项测试 —— 2026-11-13 上下文/文件修改批次"""

import os
import sys
import time
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "backend"))
os.environ["TASKS_DIR"] = str(project_root / "tasks")


class TestEditFile:
    """edit：old_text→new_text 局部替换（Hermes patch 同构精简版）"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        self.skill = FileOperationsSkill()
        self.project = f"test_edit_{int(time.time())}"
        yield
        try:
            import shutil
            d = self.skill._tasks_dir / self.project
            if d.exists():
                shutil.rmtree(d)
        except Exception:
            pass

    async def _write(self, name: str, content: str):
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        r = await FileOperationsSkill().execute(
            operation="write", path=name, content=content,
            task_path=self.project,
        )
        assert r.success, r.error
        return r

    async def _edit(self, **kw):
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        kw.setdefault("task_path", self.project)
        return await FileOperationsSkill().execute(operation="edit", **kw)

    @pytest.mark.asyncio
    async def test_unique_replace(self):
        """唯一命中：只改目标片段，其余逐字不动"""
        await self._write("app.py", "x = 1\ny = 2\nz = 3\n")
        r = await self._edit(path="app.py", old_text="y = 2", new_text="y = 22")
        assert r.success, r.error
        assert r.data["replaced"] == 1 and r.data["matches"] == 1
        body = (self.skill._tasks_dir / self.project / "app.py").read_text()
        assert body == "x = 1\ny = 22\nz = 3\n"

    @pytest.mark.asyncio
    async def test_not_found_error(self):
        """未命中：报错并提示用 search_files/read 定位"""
        await self._write("a.py", "alpha = 1\n")
        r = await self._edit(path="a.py", old_text="beta = 2", new_text="beta = 3")
        assert not r.success
        assert "未找到" in str(r.error)
        assert "search_files" in str(r.error)

    @pytest.mark.asyncio
    async def test_multi_hit_requires_replace_all(self):
        """命中多处且未给 replace_all：拒绝执行，不改文件"""
        await self._write("m.py", "k = 0\nk = 0\nk = 0\n")
        r = await self._edit(path="m.py", old_text="k = 0", new_text="k = 1")
        assert not r.success
        assert "命中" in str(r.error)
        body = (self.skill._tasks_dir / self.project / "m.py").read_text()
        assert body == "k = 0\nk = 0\nk = 0\n", "失败不得改文件"

    @pytest.mark.asyncio
    async def test_replace_all(self):
        """命中多处 + replace_all=true：全部替换"""
        await self._write("m2.py", "k = 0\nk = 0\n")
        r = await self._edit(path="m2.py", old_text="k = 0", new_text="k = 9",
                             replace_all=True)
        assert r.success, r.error
        assert r.data["replaced"] == 2
        body = (self.skill._tasks_dir / self.project / "m2.py").read_text()
        assert body == "k = 9\nk = 9\n"

    @pytest.mark.asyncio
    async def test_missing_old_text_param(self):
        await self._write("c.py", "c = 1\n")
        r = await self._edit(path="c.py", new_text="x")
        assert not r.success and "old_text" in str(r.error)

    @pytest.mark.asyncio
    async def test_nonexistent_file_error(self):
        """edit 只能改已有文件；新文件给 write 的指引"""
        r = await self._edit(path="ghost.py", old_text="a", new_text="b")
        assert not r.success
        assert "不存在" in str(r.error) and "write" in str(r.error)

    @pytest.mark.asyncio
    async def test_path_safety(self):
        """任务目录外绝对路径被拒"""
        r = await self._edit(path="/etc/hosts", old_text="x", new_text="y")
        assert not r.success
        assert "安全检查" in str(r.error)

    @pytest.mark.asyncio
    async def test_alias_maps_to_edit(self):
        """edit_file/patch 别名 → edit 局部替换（而非静默全量 write）"""
        await self._write("al.py", "keep = True\nchange = 1\n")
        r = await self.skill.execute(
            operation="edit_file", path="al.py",
            old_text="change = 1", new_text="change = 2",
            task_path=self.project,
        )
        assert r.success, r.error
        assert r.data["operation"] == "edit"
        body = (self.skill._tasks_dir / self.project / "al.py").read_text()
        assert body == "keep = True\nchange = 2\n"

    @pytest.mark.asyncio
    async def test_multiline_exact_match(self):
        """多行片段逐字匹配（含缩进换行）"""
        await self._write("f.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
        r = await self._edit(
            path="f.py",
            old_text="def f():\n    return 1",
            new_text="def f():\n    return 100",
        )
        assert r.success, r.error
        body = (self.skill._tasks_dir / self.project / "f.py").read_text()
        assert "return 100" in body and "return 2" in body
