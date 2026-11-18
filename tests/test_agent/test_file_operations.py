"""file_operations 技能专项测试"""

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


class TestFileOperationsSkill:
    """file_operations 技能测试"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        """测试前置设置"""
        from app.agent.skills.file_operations.skill import FileOperationsSkill
        self.skill = FileOperationsSkill()
        self.test_session_id = f"test_session_{int(time.time())}"
        self.test_project_name = f"test_project_{int(time.time())}"
        yield
        # 清理测试数据
        try:
            test_dir = self.skill._tasks_dir / self.test_project_name
            if test_dir.exists():
                import shutil
                shutil.rmtree(test_dir)
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_create_project_structure(self):
        """测试创建项目结构（多文件批量创建）"""
        # 使用多行格式：文件名::\n内容\n::END
        # 避免 HTML/JSON 中的特殊字符导致解析错误
        content = """app.py::
from flask import Flask
app = Flask(__name__)

@app.route('/')
def index():
    return 'Hello World'
::END
templates/index.html::
<!DOCTYPE html>
<html>
<head><title>Flask Blog</title></head>
<body><h1>Welcome</h1></body>
</html>
::END
requirements.txt::Flask>=2.0.0
"""

        result = await self.skill.execute(
            operation="create",
            path=self.test_project_name,
            content=content,
            session_id=self.test_session_id
        )

        print(f"\n[create] result: {result}")
        assert result.success, f"创建项目失败: {result.error}"

        data = result.data
        assert "path" in data, "缺少 path 字段"
        assert "project_name" in data, "缺少 project_name 字段"
        assert "files" in data, "缺少 files 字段"
        assert len(data["files"]) == 3, f"应创建 3 个文件，实际创建 {len(data['files'])} 个"

        # 验证文件是否实际存在（files 是相对项目目录的路径；create 后文件在
        # tasks/<project_name>/ 下 —— 2026-11-13 黄金测试集对齐现契约修复陈旧断言）
        project_dir = self.skill._tasks_dir / data["project_name"]
        for file_rel in data["files"]:
            file_path = project_dir / file_rel
            assert file_path.exists(), f"文件不存在: {file_path}"

        # 验证 app.py 内容
        app_py = project_dir / data["files"][0]
        content = app_py.read_text(encoding="utf-8")
        assert "from flask import Flask" in content, "app.py 内容不正确"

        # 验证 HTML 文件内容（确保多行格式解析正确）
        for f in data["files"]:
            if "html" in f.lower():
                html_file = project_dir / f
                html_content = html_file.read_text(encoding="utf-8")
                assert "<!DOCTYPE html>" in html_content, f"HTML 内容解析错误: {html_content}"

    @pytest.mark.asyncio
    async def test_write_single_file(self):
        """测试写入单个文件"""
        # 先创建项目
        project_folder = f"write_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="",
            session_id=self.test_session_id
        )
        assert create_result.success, f"创建项目失败: {create_result.error}"

        # 写入文件
        write_result = await self.skill.execute(
            operation="write",
            path="app.py",
            content="from flask import Flask",
            task_path=create_result.data.get("project_name"),
            session_id=self.test_session_id
        )

        print(f"\n[write] result: {write_result}")
        assert write_result.success, f"写入文件失败: {write_result.error}"

        # 验证文件存在
        project_dir = self.skill._tasks_dir / create_result.data.get("project_name")
        file_path = project_dir / "app.py"
        assert file_path.exists(), f"文件不存在: {file_path}"
        content = file_path.read_text(encoding="utf-8")
        assert "from flask import Flask" in content, f"文件内容不正确: {content}"

        # 清理
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_read_file(self):
        """测试读取文件"""
        # 先创建并写入文件
        project_folder = f"read_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="config.json::{\"name\": \"test\", \"version\": \"1.0.0\"}",
            session_id=self.test_session_id
        )
        assert create_result.success

        # 获取创建的文件路径
        project_name = create_result.data.get("project_name")
        created_files = create_result.data.get("files", [])
        config_file = created_files[0] if created_files else "config.json"

        # 读取文件（created_files 相对项目目录）
        file_abs_path = str(self.skill._tasks_dir / project_name / config_file)
        read_result = await self.skill.execute(
            operation="read",
            path=file_abs_path,
            session_id=self.test_session_id
        )

        print(f"\n[read] result: {read_result}")
        assert read_result.success, f"读取文件失败: {read_result.error}"
        assert "test" in str(read_result.data.get("content", "")), "读取内容不正确"

        # 清理
        import shutil
        project_dir = self.skill._tasks_dir / project_name
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_list_directory(self):
        """测试列目录"""
        # 先创建项目
        project_folder = f"list_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="file1.py::pass\nfile2.py::pass",
            session_id=self.test_session_id
        )
        assert create_result.success

        # 列出目录
        project_name = create_result.data.get("project_name")
        list_result = await self.skill.execute(
            operation="list",
            path=str(self.skill._tasks_dir / project_name),
            session_id=self.test_session_id
        )

        print(f"\n[list] result: {list_result}")
        assert list_result.success, f"列目录失败: {list_result.error}"
        assert "items" in list_result.data, "缺少 items 字段"
        assert len(list_result.data["items"]) >= 2, f"应至少列出 2 个文件，实际 {len(list_result.data['items'])} 个"

        # 清理
        import shutil
        project_dir = self.skill._tasks_dir / project_name
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_delete_file(self):
        """测试删除文件"""
        # 先创建项目
        project_folder = f"delete_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="temp.txt::delete me",
            session_id=self.test_session_id
        )
        assert create_result.success

        # 获取创建的文件路径
        project_name = create_result.data.get("project_name")
        created_files = create_result.data.get("files", [])
        temp_file = created_files[0] if created_files else "temp.txt"
        file_abs_path = str(self.skill._tasks_dir / project_name / temp_file)

        # 删除文件
        delete_result = await self.skill.execute(
            operation="delete",
            path=file_abs_path,
            session_id=self.test_session_id
        )

        print(f"\n[delete] result: {delete_result}")
        assert delete_result.success, f"删除文件失败: {delete_result.error}"

        # 验证文件不存在
        file_path = Path(file_abs_path)
        assert not file_path.exists(), f"文件未删除: {file_path}"

        # 清理
        import shutil
        project_dir = self.skill._tasks_dir / project_name
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_move_file(self):
        """测试 move：移动后原位置消失、目标位置存在（归类任务核心语义）"""
        project_folder = f"move_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="main.py::print('hello')\nconfig.py::DEBUG = True",
            session_id=self.test_session_id
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        move_result = await self.skill.execute(
            operation="move",
            path="main.py",
            dest="backend/main.py",
            task_path=project_name,
            session_id=self.test_session_id
        )
        print(f"\n[move] result: {move_result}")
        assert move_result.success, f"移动失败: {move_result.error}"
        assert move_result.data.get("moved") is True

        project_dir = self.skill._tasks_dir / project_name
        assert not (project_dir / "main.py").exists(), "原位置文件未消失（移动语义失效）"
        assert (project_dir / "backend" / "main.py").exists(), "目标位置文件不存在"
        assert "hello" in (project_dir / "backend" / "main.py").read_text(encoding="utf-8")

        # 别名 mv 等价
        mv_result = await self.skill.execute(
            operation="mv",
            path="config.py",
            dest="backend/config.py",
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert mv_result.success, f"mv 别名失败: {mv_result.error}"
        assert not (project_dir / "config.py").exists()
        assert (project_dir / "backend" / "config.py").exists()

        # 清理
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    async def test_move_batch_files_array(self):
        """move 支持 files 数组批量（任务93重构生产回归：原先7次"缺少 path"）"""
        project_folder = f"move_batch_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="a.py::A = 1\nb.py::B = 2\ncfg.py::C = 3",
            session_id=self.test_session_id
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        batch = await self.skill.execute(
            operation="move",
            files=[
                {"path": "a.py", "destination": "backend/a.py"},
                {"from": "b.py", "to": "backend/b.py"},
                {"src": "cfg.py", "dst": "backend/cfg.py"},
            ],
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert batch.success, f"批量移动失败: {batch.error}"
        assert batch.data.get("count") == 3
        project_dir = self.skill._tasks_dir / project_name
        for f in ("a.py", "b.py", "cfg.py"):
            assert not (project_dir / f).exists(), f"{f} 原位置未消失"
            assert (project_dir / "backend" / f).exists(), f"backend/{f} 不存在"

    async def test_move_batch_partial_failure(self):
        """批量移动：一项源不存在 → 其余照常成功，失败项进 note"""
        project_folder = f"move_batch_partial_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="keep.py::KEEP = 1",
            session_id=self.test_session_id
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        batch = await self.skill.execute(
            operation="move",
            files=[
                {"path": "keep.py", "dest": "backend/keep.py"},
                {"path": "ghost_does_not_exist.py", "dest": "backend/ghost.py"},
            ],
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert batch.success, f"部分失败不应整体失败: {batch.error}"
        assert batch.data.get("count") == 1
        assert batch.data.get("note"), "失败项应记录在 note"
        project_dir = self.skill._tasks_dir / project_name
        assert (project_dir / "backend" / "keep.py").exists()

    @pytest.mark.asyncio
    async def test_edit_batch_files_array(self):
        """edit 支持 files 数组批量（TC-S16-03 生产回归：2026-11-14 01:39
        两次"缺少 path"——模型把 files 批量推广到 edit 且用 old_string 键）"""
        project_folder = f"edit_batch_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="a.py::A = 1\nb.py::B = 2",
            session_id=self.test_session_id,
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        batch = await self.skill.execute(
            operation="edit",
            files=[
                {"path": "a.py", "old_string": "A = 1", "new_string": "A = 111"},
                {"path": "b.py", "old_string": "B = 2", "new_string": "B = 222"},
            ],
            task_path=project_name,
            session_id=self.test_session_id,
        )
        assert batch.success, f"批量编辑失败: {batch.error}"
        project_dir = self.skill._tasks_dir / project_name
        assert "A = 111" in (project_dir / "a.py").read_text(), "a.py 未被批量编辑"
        assert "B = 222" in (project_dir / "b.py").read_text(), "b.py 未被批量编辑"

    async def test_delete_batch_files_and_paths(self):
        """delete 支持 files=[{path}] 与 paths=[...] 批量（TC-S16-01 取证修复）。"""
        project_folder = f"del_batch_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="a.py::A=1\nb.py::B=2\nc.py::C=3",
            session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name

        # files 数组（dict）删 a、b
        r1 = await self.skill.execute(
            operation="delete",
            files=[{"path": "a.py"}, {"path": "b.py"}],
            task_path=project_name, session_id=self.test_session_id)
        assert r1.success, r1.error
        assert r1.data.get("count") == 2
        assert not (project_dir / "a.py").exists()
        assert not (project_dir / "b.py").exists()

        # paths 数组（字符串）删 c
        r2 = await self.skill.execute(
            operation="delete", paths=["c.py"],
            task_path=project_name, session_id=self.test_session_id)
        assert r2.success, r2.error
        assert not (project_dir / "c.py").exists()

        # 部分失败：源不存在的项进 note，其余照删
        (project_dir / "keep.py").write_text("k")
        r3 = await self.skill.execute(
            operation="delete", paths=["keep.py", "ghost.py"],
            task_path=project_name, session_id=self.test_session_id)
        assert r3.success, r3.error
        assert not (project_dir / "keep.py").exists()

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

        # 清理
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_delete_batch_cascades_empty_dirs(self):
        """批量删除后空目录树级联清掉，任务根保留（TC-S16-01 残留取证）。"""
        project_folder = f"del_cascade_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="static/css/style.css::body{}\ntemplates/base.html::x\nroot.txt::keep",
            session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        assert (project_dir / "static" / "css" / "style.css").exists()

        r = await self.skill.execute(
            operation="delete",
            files=[{"path": "static/css/style.css"}, {"path": "templates/base.html"}],
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, r.error
        # css → static、templates 整条链都空出 → 全部级联删除
        assert not (project_dir / "static").exists(), "static 空目录树残留"
        assert not (project_dir / "templates").exists(), "templates 空目录残留"
        # 根目录与根下文件绝不动
        assert (project_dir / "root.txt").exists()

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_execute_recovers_truncated_raw(self):
        """params 被截断降级 {"raw":...} → 抢救 files[] 完整元素先落盘。

        2026-11-13 TC-S16-01 生产取证：批量写 13.6KB 被输出上限截断，
        解析降级 raw → 恒"缺少 path"烧光轮次；完整元素必须照常写入。
        """
        project_folder = f"raw_recovery_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="x::X", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        # 模拟：第一元素完整，第二元素字符串没闭合（截断点）
        truncated_raw = (
            '{"operation": "write", "files": '
            '[{"path": "a.py", "content": "A=1"}, '
            '{"path": "b.py", "content": "B=2 未闭合')
        result = await self.skill.execute(
            raw=truncated_raw, task_path=project_name,
            session_id=self.test_session_id)
        assert result.success, result.error
        project_dir = self.skill._tasks_dir / project_name
        assert (project_dir / "a.py").read_text(encoding="utf-8") == "A=1"
        assert not (project_dir / "b.py").exists(), "截断元素不应落盘"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_path_with_task_dir_prefix_resolves_inside_task(self):
        """路径带任务目录名前缀 → 剥前缀后在任务目录内解析（2026-11-13 用户
        反馈：查找时没带/重复带任务目录 → 嵌套或落 tasks 根 → 获取不到文件）。"""
        project_folder = f"prefix_strip_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="app/views/x.py::V", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name

        # ① 单 path 带任务目录前缀读取 → 剥前缀后必须读到
        r = await self.skill.execute(
            operation="read", path=f"{project_name}/app/views/x.py",
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"带前缀 read 应成功: {r.error}"

        # ② 批量 files[].path 带前缀写入 → 落任务目录内，不许嵌套出同名子目录
        r2 = await self.skill.execute(
            operation="write",
            files=[{"path": f"{project_name}/app/views/y.py", "content": "Y"}],
            task_path=project_name, session_id=self.test_session_id)
        assert r2.success, r2.error
        assert (project_dir / "app" / "views" / "y.py").exists(), "前缀没剥导致嵌套写盘"
        assert not (project_dir / project_name).exists()

        # ③ tasks/<task>/x 变体同样剥
        r3 = await self.skill.execute(
            operation="read", path=f"tasks/{project_name}/app/views/x.py",
            task_path=project_name, session_id=self.test_session_id)
        assert r3.success, f"tasks/ 前缀变体应成功: {r3.error}"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_move_cascades_empty_source_chain(self):
        """move 搬空后源目录链级联清掉（css→static→app 整链，2026-11-13）。"""
        project_folder = f"move_cascade_test_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="app/static/css/x.css::body{}\napp/main.py::M",
            session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name

        result = await self.skill.execute(
            operation="move", path="app/static/css/x.css",
            dest="backend/css/x.css", task_path=project_name,
            session_id=self.test_session_id)
        assert result.success, result.error
        assert (project_dir / "backend" / "css" / "x.css").exists()
        # static、css、app 逐层空出 → 整链消失（app/main.py 还在时 app 保留）
        assert not (project_dir / "app" / "static").exists(), "app/static 空壳残留"
        assert (project_dir / "backend" / "css").exists(), "目标侧必须保留"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_move_overwrites_existing_dest(self):
        """目标已存在且内容不同 → 按 shell mv 语义覆盖（生产实测：拒绝会让模型
        绕进 read/write 死循环烧满轮次）；目录冲突与缺 dest 仍拒绝"""
        project_folder = f"move_conflict_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="a.py::A = 1\nbackend/b.py::B = 2",
            session_id=self.test_session_id
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        r = await self.skill.execute(
            operation="move",
            path="a.py",
            dest="backend/b.py",
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert r.success, f"文件覆盖移动应成功: {r.error}"
        project_dir = self.skill._tasks_dir / project_name
        assert not (project_dir / "a.py").exists(), "源应消失"
        assert (project_dir / "backend" / "b.py").read_text() == "A = 1", "目标应为源内容"
        assert "覆盖" in str(r.data.get("note", "")), "应提示覆盖了不同内容"

        # 缺 dest 参数 → 明确报错（而非静默什么都不做）
        r2 = await self.skill.execute(
            operation="move",
            path="backend/b.py",
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert not r2.success
        assert "dest" in str(r2.error)

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_move_destination_alias(self):
        """模型常用 destination 作目标参数（2026-11-13 生产实测）→ 必须接受"""
        project_folder = f"move_alias_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="a.py::A = 1", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")

        r = await self.skill.execute(
            operation="move", path="a.py", destination="backend/a.py",
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"destination 别名未被接受: {r.error}"
        project_dir = self.skill._tasks_dir / project_name
        assert (project_dir / "backend" / "a.py").exists()
        assert not (project_dir / "a.py").exists()

        # 缺 dest 时错误文案要含"缺少/参数"（触发 planner 全量 schema 注入）
        r2 = await self.skill.execute(
            operation="move", path="backend/a.py",
            task_path=project_name, session_id=self.test_session_id)
        assert not r2.success
        assert "缺少" in str(r2.error) and "参数" in str(r2.error)

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_move_over_empty_shell_target(self):
        """目标是 0 字节空壳（先前失败轮的 write 产物）→ 直接覆盖移动，不再拒绝烧轮"""
        project_folder = f"move_emptydst_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="main.py::print('x')", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        (project_dir / "backend").mkdir()
        (project_dir / "backend" / "main.py").write_bytes(b"")  # 0 字节空壳

        r = await self.skill.execute(
            operation="move", path="main.py", dest="backend/main.py",
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"空壳目标应可覆盖: {r.error}"
        assert (project_dir / "backend" / "main.py").read_text() == "print('x')"
        assert not (project_dir / "main.py").exists()

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_move_identical_target_idempotent(self):
        """目标与源内容相同 = 已在目标位置 → 删源、判移动成功（幂等）"""
        project_folder = f"move_samedst_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="cfg.py::X = 1", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        (project_dir / "backend").mkdir()
        (project_dir / "backend" / "cfg.py").write_text("X = 1")  # 同内容

        r = await self.skill.execute(
            operation="move", path="cfg.py", dest="backend/cfg.py",
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"同内容目标应幂等成功: {r.error}"
        assert r.data.get("moved") is True
        assert not (project_dir / "cfg.py").exists(), "源应被删除"
        assert (project_dir / "backend" / "cfg.py").exists()

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_move_cleans_emptied_source_dir(self):
        """move 搬空源目录后自动删除空文件夹（2026-11-13 用户反馈：
        改造任务原文件搬走了，旧空文件夹残留）"""
        project_folder = f"move_clean_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="placeholder.txt::x", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        (project_dir / "old").mkdir()
        (project_dir / "old" / "a.txt").write_text("AAA", encoding="utf-8")
        (project_dir / "old" / "b.txt").write_text("BBB", encoding="utf-8")

        # 还剩 b.txt 时 old/ 必须保留
        r1 = await self.skill.execute(
            operation="move", path="old/a.txt", dest="docs/a.txt",
            task_path=project_name, session_id=self.test_session_id)
        assert r1.success, r1.error
        assert (project_dir / "old").exists(), "目录非空时必须保留"
        assert not (project_dir / "old" / "a.txt").exists()

        # 搬走最后一个文件 → 空 old/ 被清理
        r2 = await self.skill.execute(
            operation="move", path="old/b.txt", dest="docs/b.txt",
            task_path=project_name, session_id=self.test_session_id)
        assert r2.success, r2.error
        assert not (project_dir / "old").exists(), "搬空后旧空文件夹应被自动清理"
        assert (project_dir / "docs" / "b.txt").exists()
        assert "已清理空目录" in str(r2.data.get("note", "")), f"note 应记录清理: {r2.data}"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_write_batch_files_parallel(self):
        """write 支持 files 数组批量并发写入（2026-11-13 用户反馈：
        项目骨架原先逐文件多轮创建，互不关联文件应一次并发建完）"""
        project_folder = f"batch_write_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="placeholder.txt::x", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name

        r = await self.skill.execute(
            operation="write",
            files=[
                {"path": "config.py", "content": "CFG = 1"},
                {"path": "app/__init__.py", "content": "def create_app(): ..."},
                {"path": "requirements.txt", "content": "Flask>=3.0"},
            ],
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"批量写入失败: {r.error}"
        assert r.data.get("count") == 3, f"应写入3个文件: {r.data}"
        assert (project_dir / "config.py").exists()
        assert (project_dir / "app" / "__init__.py").exists(), "子目录应自动创建"
        assert (project_dir / "requirements.txt").exists()
        assert (project_dir / "config.py").read_text(encoding="utf-8") == "CFG = 1"

        # 单文件失败不拖垮整批（非法路径内容的文件失败，其余成功）
        await self.skill.execute(
            operation="write",
            files=[{"path": "ok1.py", "content": "A"},
                   {"path": "../escape.py", "content": "B"}],
            task_path=project_name, session_id=self.test_session_id)
        # ../ 出任务目录应被安全检查拒绝或被规范化；两种情况都必须保证 ok1 落盘
        assert (project_dir / "ok1.py").exists(), "合法文件必须写入成功"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_read_batch_files_parallel(self):
        """read 支持 files 数组并行读取（与 write 对称；2026-11-13 生产实测
        模型把 files 推广到 read，read 不收会报"缺少 path 参数"浪费一轮）"""
        project_folder = f"batch_read_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="a.txt::AAA内容\nb.txt::BBB内容",
            session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name

        r = await self.skill.execute(
            operation="read",
            files=[{"path": "a.txt"}, {"path": "b.txt"}],
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, f"批量读取失败: {r.error}"
        assert r.data.get("count") == 2, f"应读到2个文件: {r.data}"
        body = r.data.get("content", "")
        assert "AAA内容" in body and "BBB内容" in body, f"拼接内容缺失: {body[:200]}"
        assert "a.txt" in body and "b.txt" in body, "应有文件路径分隔标记"

        # 全部不存在 → 失败且报清楚
        r2 = await self.skill.execute(
            operation="read",
            files=[{"path": "no1.txt"}, {"path": "no2.txt"}],
            task_path=project_name, session_id=self.test_session_id)
        assert not r2.success, "全部失败时应返回失败"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_edit_batch_edits_array(self):
        """edit 支持 edits 数组批量局部替换（2026-11-13 用户测试：模型把
        write 的 files 批量模式自然推广到 edit，发 edits:[{old,new}]，
        原先报"缺少 old_text"白烧整轮预算）"""
        project_folder = f"edit_batch_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder, content="seed.txt::seed",
            session_id=self.test_session_id,
        )
        assert create_result.success, create_result.error
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        (project_dir / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
        (project_dir / "b.py").write_text("bee", encoding="utf-8")

        result = await self.skill.execute(
            operation="edit", path="a.py",
            edits=[
                {"old": "line1", "new": "LINE1"},
                {"old_text": "line3", "new_text": "LINE3"},   # 兼容键
                {"path": "b.py", "old": "bee", "new": "BEE"},  # 逐项 path
            ],
            task_path=project_name, session_id=self.test_session_id,
        )
        assert result.success, result.error
        assert result.data["count"] == 3
        a_txt = (project_dir / "a.py").read_text(encoding="utf-8")
        assert "LINE1" in a_txt and "LINE3" in a_txt
        assert "BEE" in (project_dir / "b.py").read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_delete_cleans_emptied_parent_dir(self):
        """delete 删光目录内文件后，空父目录同样自动清理"""
        project_folder = f"del_clean_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create", path=project_folder,
            content="placeholder.txt::x", session_id=self.test_session_id)
        assert create_result.success
        project_name = create_result.data.get("project_name")
        project_dir = self.skill._tasks_dir / project_name
        (project_dir / "tmpdir").mkdir()
        (project_dir / "tmpdir" / "a.txt").write_text("A", encoding="utf-8")

        r = await self.skill.execute(
            operation="delete", path="tmpdir/a.txt",
            task_path=project_name, session_id=self.test_session_id)
        assert r.success, r.error
        assert not (project_dir / "tmpdir").exists(), "删空后父目录应被自动清理"

        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_read_missing_suggests_same_name_in_subdir(self):
        """裸名读取失败时，若同名文件在子目录 → 错误信息直接给出正确相对路径
        （生产实测 app/extensions.py 存在、模型按裸名读失败 4 次，
        旧提示还引导 write 建根目录重复文件）"""
        project_folder = f"read_suggest_{int(time.time())}"
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="app/extensions.py::db = None",
            session_id=self.test_session_id
        )
        assert create_result.success
        project_name = create_result.data.get("project_name")

        r = await self.skill.execute(
            operation="read",
            path="extensions.py",
            task_path=project_name,
            session_id=self.test_session_id
        )
        assert not r.success
        assert "同名文件实际位于: app/extensions.py" in str(r.error), r.error
        assert "operation='write' 创建" not in str(r.error), "同名文件存在时不得引导创建"

        import shutil
        project_dir = self.skill._tasks_dir / project_name
        if project_dir.exists():
            shutil.rmtree(project_dir)

    @pytest.mark.asyncio
    async def test_operation_aliases(self):
        """测试操作别名映射"""
        # 测试 write_file 别名
        result = await self.skill.execute(
            operation="write_file",
            path="test.txt",
            content="test content",
            session_id=self.test_session_id
        )
        # 别名应该被映射，不应该报错"不支持的操作"
        assert result.success or "不支持的操作" not in str(result.error), \
            f"操作别名映射失败: {result.error}"

    @pytest.mark.asyncio
    async def test_safe_path_check(self):
        """测试路径安全检查"""
        # 尝试写入 backend 目录（应该被拒绝）
        unsafe_path = str(Path(__file__).parent.parent.parent / "backend" / "app" / "test.py")
        result = await self.skill.execute(
            operation="write",
            path=unsafe_path,
            content="dangerous",
            session_id=self.test_session_id
        )

        print(f"\n[safe_check] result: {result}")
        # 应该被安全检查拒绝
        if not result.success:
            assert "安全检查失败" in str(result.error), "应该拒绝不安全的路径"

    @pytest.mark.asyncio
    async def test_session_limit(self):
        """测试会话限制"""
        session_id = f"limit_test_{int(time.time())}"
        project_folder = f"limited_project_{int(time.time())}"

        # 创建项目
        create_result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content="main.py::pass",
            session_id=session_id
        )
        assert create_result.success
        created_project_name = create_result.data.get("project_name")

        # 尝试在另一个项目目录下创建文件（应该被拒绝）
        another_project = f"another_{int(time.time())}"
        write_result = await self.skill.execute(
            operation="write",
            path="new_file.py",
            content="new content",
            task_path=another_project,
            session_id=session_id
        )

        print(f"\n[session_limit] result: {write_result}")
        # 应该被会话限制拒绝（只能操作已创建的项目）
        if not write_result.success:
            assert "会话已限制" in str(write_result.error) or "安全检查失败" in str(write_result.error), \
                f"会话限制未生效: {write_result.error}"

        # 清理
        import shutil
        for folder in [created_project_name, another_project]:
            folder_path = self.skill._tasks_dir / folder
            if folder_path.exists():
                shutil.rmtree(folder_path)

    @pytest.mark.asyncio
    async def test_nested_directory_creation(self):
        """测试嵌套目录创建"""
        project_folder = f"nested_test_{int(time.time())}"
        # 使用多行格式，避免内容中的冒号被误解析
        content = """src/__init__.py::
pass
::END
src/models/__init__.py::
pass
::END
src/models/user.py::
class User:
    pass
::END
src/views/__init__.py::
pass
::END
src/views/home.py::
def home():
    return 'Home'
::END
"""

        result = await self.skill.execute(
            operation="create",
            path=project_folder,
            content=content,
            session_id=self.test_session_id
        )

        print(f"\n[nested] result: {result}")
        assert result.success, f"创建嵌套目录失败: {result.error}"

        # 验证创建的文件列表正确
        created_files = result.data.get("files", [])
        print(f"创建的文件: {created_files}")

        # 验证所有嵌套目录都创建
        project_dir = self.skill._tasks_dir / result.data.get("project_name")
        for rel_path in ["src", "src/models", "src/views"]:
            dir_path = project_dir / rel_path
            assert dir_path.exists(), f"目录不存在: {dir_path}"
            assert dir_path.is_dir(), f"不是目录: {dir_path}"

        # 验证关键文件存在
        expected_files = ["src/__init__.py", "src/models/user.py", "src/views/home.py"]
        for expected in expected_files:
            file_path = project_dir / expected
            assert file_path.exists(), f"文件不存在: {file_path}"
            content = file_path.read_text(encoding="utf-8")
            assert len(content) > 0, f"文件为空: {file_path}"
            print(f"  - {expected}: {len(content)} bytes")

        # 清理
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)


class TestFileOperationsIntegration:
    """file_operations 集成测试"""

    @pytest.mark.asyncio
    async def test_full_flask_blog_workflow(self):
        """测试完整的 Flask 博客项目创建流程"""
        session_id = f"flask_test_{int(time.time())}"

        from app.agent.skills.file_operations.skill import FileOperationsSkill
        skill = FileOperationsSkill()

        # 1. 创建项目结构（使用多行格式）
        create_result = await skill.execute(
            operation="create",
            path="Flask_Blog",
            content="""app.py::
from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'

# 模拟数据
posts = []

@app.route('/')
def index():
    return render_template('index.html', posts=posts)

if __name__ == '__main__':
    app.run(debug=True)
::END
templates/base.html::
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}Flask Blog{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <header><h1><a href="/">Flask Blog</a></h1></header>
    <main>{% block content %}{% endblock %}</main>
</body>
</html>
::END
templates/index.html::
{% extends "base.html" %}
{% block title %}首页{% endblock %}
{% block content %}
<h2>博客文章</h2>
{% for post in posts %}
<article>
    <h3>{{ post.title }}</h3>
    <p>{{ post.content }}</p>
    <small>{{ post.date }}</small>
</article>
{% endfor %}
{% endblock %}
::END
static/style.css::
body {
    font-family: Arial, sans-serif;
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}
header {
    border-bottom: 2px solid #333;
    margin-bottom: 20px;
}
article {
    border: 1px solid #ddd;
    padding: 15px;
    margin-bottom: 15px;
}
::END
requirements.txt::Flask>=2.0.0
""",
            session_id=session_id
        )

        print(f"\n[integration] create result: {create_result}")
        assert create_result.success, f"创建项目失败: {create_result.error}"

        project_name = create_result.data.get("project_name")
        print(f"项目名称: {project_name}")

        # 验证创建的文件
        created_files = create_result.data.get("files", [])
        print(f"创建的文件: {created_files}")
        assert len(created_files) == 5, f"应创建 5 个文件，实际创建 {len(created_files)} 个"

        # 验证每个文件存在且内容正确
        # created_files 是相对项目目录的路径（2026-11-13 黄金测试集对齐现契约）
        project_dir = skill._tasks_dir / project_name
        for rel_file in created_files:
            file_path = project_dir / rel_file
            assert file_path.exists(), f"文件不存在: {file_path}"
            content = file_path.read_text(encoding="utf-8")
            assert len(content) > 0, f"文件为空: {file_path}"
            print(f"  - {rel_file}: {len(content)} bytes")

        # 2. 列出目录，验证结构
        list_result = await skill.execute(
            operation="list",
            path=str(project_dir),
            session_id=session_id
        )
        print(f"\n[integration] list result: {list_result}")
        assert list_result.success

        items = list_result.data.get("items", [])
        item_names = [item["name"] for item in items]
        print(f"目录内容: {item_names}")

        # 应该有 templates 和 static 目录
        assert "templates" in item_names, "缺少 templates 目录"
        assert "static" in item_names, "缺少 static 目录"

        # 清理
        import shutil
        if project_dir.exists():
            shutil.rmtree(project_dir)
            print(f"\n已清理测试项目: {project_dir}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
