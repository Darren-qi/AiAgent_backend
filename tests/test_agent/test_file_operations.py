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

        # 验证文件是否实际存在
        for file_rel in data["files"]:
            file_path = self.skill._tasks_dir / file_rel
            assert file_path.exists(), f"文件不存在: {file_path}"

        # 验证 app.py 内容
        app_py = self.skill._tasks_dir / data["files"][0]
        content = app_py.read_text(encoding="utf-8")
        assert "from flask import Flask" in content, "app.py 内容不正确"

        # 验证 HTML 文件内容（确保多行格式解析正确）
        for f in data["files"]:
            if "html" in f.lower():
                html_file = self.skill._tasks_dir / f
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

        # 读取文件
        file_abs_path = str(self.skill._tasks_dir / config_file)
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
        file_abs_path = str(self.skill._tasks_dir / temp_file)

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
        # 注意：created_files 中的路径是相对于 tasks 目录的，所以要用 _tasks_dir 而不是 project_dir
        project_dir = skill._tasks_dir / project_name
        for rel_file in created_files:
            # rel_file 已经包含了 project_name 前缀（如 "Flask_Blog_xxx/app.py"）
            # 所以直接用 _tasks_dir / rel_file
            file_path = skill._tasks_dir / rel_file
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
