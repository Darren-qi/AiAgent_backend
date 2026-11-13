"""search_files 技能 + read 分页（先搜后读）专项测试"""

import os
import sys
import time
import pytest
from pathlib import Path

# 设置项目根目录
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "backend"))

# 设置环境变量
os.environ["TASKS_DIR"] = str(project_root / "tasks")


class TestReadPagination:
    """read offset/limit 分页 + 行号"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        self.skill = FileOperationsSkill()
        self.project = f"test_pager_{int(time.time())}"
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

    @pytest.mark.asyncio
    async def test_default_read_first_page_with_line_numbers(self):
        """默认读前 200 行：带行号 + 总行数 + 续读提示"""
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        body = "\n".join(f"line_{i} = {i}" for i in range(1, 301))  # 300 行
        await self._write("big.py", body)

        r = await FileOperationsSkill().execute(
            operation="read", path="big.py", task_path=self.project)
        assert r.success, r.error
        data = r.data
        assert data["total_lines"] == 300
        assert data["offset"] == 1
        assert data["has_more"] is True
        assert data["next_offset"] == 201
        assert "line_1" in data["content"]
        assert "line_200" in data["content"]
        assert "line_201" not in data["content"]
        assert "共 300 行" in data["content"]
        # 行号前缀存在（Hermes 风格，便于精确定位）
        assert "| line_1 = 1" in data["content"]

    @pytest.mark.asyncio
    async def test_offset_continuation(self):
        """offset 续读到文件末尾"""
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        body = "\n".join(f"line_{i}" for i in range(1, 301))
        await self._write("big2.py", body)

        r = await FileOperationsSkill().execute(
            operation="read", path="big2.py", task_path=self.project,
            offset=250, limit=100)
        assert r.success, r.error
        data = r.data
        assert data["total_lines"] == 300
        assert data["has_more"] is False
        assert data["next_offset"] is None
        assert "line_250" in data["content"]
        assert "line_300" in data["content"]

    @pytest.mark.asyncio
    async def test_small_file_single_page(self):
        """小文件整页读完，has_more=False"""
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        await self._write("small.py", "a = 1\nb = 2\n")
        r = await FileOperationsSkill().execute(
            operation="read", path="small.py", task_path=self.project)
        assert r.success, r.error
        assert r.data["total_lines"] == 2
        assert r.data["has_more"] is False
        assert "已到文件末尾" in r.data["content"]


class TestSearchFiles:
    """search_files 技能：内容搜索 / 文件名搜索 / 安全边界"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        from app.agent.skills.search_files.skill import SearchFilesSkill
        self.skill = SearchFilesSkill()
        self.project = f"test_search_{int(time.time())}"
        # 造测试数据：任务目录结构
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        files = {
            "api.py": "def delete_post(post_id):\n    return post_id\n\ndef get_post(post_id):\n    pass\n",
            "models.py": "class Post:\n    pass\n\nclass User:\n    def remove(self):\n        pass\n",
            "src/util.js": "export function deleteUser(id) {\n  return id;\n}\n",
            "README.md": "# demo\ndelete stuff here\n",
        }
        for path, content in files.items():
            r = await FileOperationsSkill().execute(
                operation="write", path=path, content=content,
                task_path=self.project)
            assert r.success, f"{path}: {r.error}"
        yield
        try:
            import shutil
            d = FileOperationsSkill()._tasks_dir / self.project
            if d.exists():
                shutil.rmtree(d)
        except Exception:
            pass

    async def _search(self, **kw):
        kw.setdefault("task_path", self.project)
        return await self.skill.execute(**kw)

    @pytest.mark.asyncio
    async def test_content_search_returns_file_line_snippet(self):
        r = await self._search(pattern=r"def delete|function deleteUser")
        assert r.success, r.error
        d = r.data
        assert d["total_matches"] == 2
        assert d["files_hit"] == 2
        joined = "\n".join(d["matches"])
        assert "api.py:1:" in joined
        assert "util.js:1:" in joined

    @pytest.mark.asyncio
    async def test_output_mode_count(self):
        r = await self._search(pattern=r"def |class ", output_mode="count")
        assert r.success, r.error
        joined = "\n".join(r.data["matches"])
        assert "api.py" in joined
        assert r.data["total_matches"] >= 4

    @pytest.mark.asyncio
    async def test_output_mode_files_only(self):
        r = await self._search(pattern=r"delete", output_mode="files_only")
        assert r.success, r.error
        # api.py(delete_post)、README.md(delete stuff)、src/util.js(deleteUser) 均含 delete
        assert set(r.data["matches"]) == {"api.py", "README.md", "src/util.js"}

    @pytest.mark.asyncio
    async def test_file_glob_filter(self):
        r = await self._search(pattern=r"delete", file_glob="*.py")
        assert r.success, r.error
        assert r.data["files_hit"] == 1
        assert r.data["matches"][0].startswith("api.py:")

    @pytest.mark.asyncio
    async def test_target_files_glob(self):
        r = await self._search(pattern="*.js", target="files")
        assert r.success, r.error
        assert r.data["matches"] == ["src/util.js"]

    @pytest.mark.asyncio
    async def test_path_escape_rejected(self):
        """绝对路径/越出任务目录 → 安全检查失败"""
        r = await self._search(pattern="def", path="/etc")
        assert not r.success
        assert "安全检查失败" in str(r.error)

    @pytest.mark.asyncio
    async def test_invalid_regex_error(self):
        r = await self._search(pattern="(unclosed")
        assert not r.success
        assert "正则" in str(r.error)

    @pytest.mark.asyncio
    async def test_mode_alias_filename(self):
        """模型常传 mode:"filename"（生产实测）→ 别名归一到 target=files"""
        r = await self._search(pattern="*.py", mode="filename")
        assert r.success, r.error
        assert "api.py" in r.data["matches"] and "models.py" in r.data["matches"]

    @pytest.mark.asyncio
    async def test_glob_pattern_fallback(self):
        """pattern 是文件名 glob（*.py）却按正则编译 → 降级按文件名搜，不再硬报错浪费一轮"""
        r = await self._search(pattern="*.py")
        assert r.success, r.error
        assert "api.py" in r.data["matches"]
        assert "glob" in (r.data.get("note") or "")

    @pytest.mark.asyncio
    async def test_type_alias_content(self):
        """模型传 type:"content"（生产实测）→ 等价 target=content"""
        r = await self._search(pattern="def delete_post", type="content")
        assert r.success, r.error
        assert r.data["total_matches"] >= 1

    @pytest.mark.asyncio
    async def test_missing_pattern_lists_directory(self):
        """未提供 pattern（生产实测反复"缺少 pattern 参数"且 planner 跳过观察）
        → 降级为列出目录文件，不再报错烧轮"""
        r = await self._search(pattern="")
        assert r.success, r.error
        assert "api.py" in r.data["matches"]
        assert "未提供 pattern" in (r.data.get("note") or "")

    @pytest.mark.asyncio
    async def test_zero_hit_note(self):
        r = await self._search(pattern=r"zzz_not_exist_qqq")
        assert r.success, r.error
        assert r.data["total_matches"] == 0
        assert "0 命中" in r.data["note"]


class TestSearchFilesRegistration:
    """新技能对 planner 可见（渐进式加载器自动扫描）"""

    @pytest.mark.asyncio
    async def test_loader_indexes_search_files(self):
        from app.agent.skills.core.progressive_loader import get_loader
        loader = get_loader()
        schemas = loader.get_schemas()
        names = [s.get("name") for s in schemas]
        assert "search_files" in names, f"未注册: {names}"
        # SKILL.md frontmatter 必须完整解析（YAML 冒号等曾导致 schema 降级）
        sch = next(s for s in schemas if s.get("name") == "search_files")
        props = ((sch.get("parameters") or {}).get("properties")) or {}
        assert "pattern" in props, f"参数 schema 丢失（frontmatter 解析失败）: {sch}"
        assert "关键词" in (sch.get("description") or "")
        # 技能清单字符串里也要有（planner 的"## 可用工具"段）
        assert "search_files" in loader.get_skill_list_str()
