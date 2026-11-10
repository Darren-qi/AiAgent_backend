"""Sandbox Skill - 受限沙箱执行 Python（运行测试/验证脚本）。

安全模型与 AutoGen 后端 security/sandbox.py 的 restricted 模式对齐（本机与
生产均无 Docker，故只实现 restricted）：
  - 无 shell：subprocess.run(argv=[...])，shell=False
  - python -I 隔离模式（不加载用户 site/PYTHONPATH/环境变量）
  - cwd 锁定在任务目录，HOME 也指向该目录
  - 最小化环境变量，stdin=DEVNULL
  - 超时强杀，stdout/stderr 截断
受限模式不是强安全边界（代码仍可访问绝对路径），与 AutoGen 后端同一风险面。
文件模式用 -E -s 而非 -I：-I 会把脚本目录排除出 sys.path，
同目录模块（import calculator）会 ModuleNotFoundError；-E -s 仍屏蔽
环境变量与用户 site-packages。
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from app.agent.skills.core.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 60
STDOUT_LIMIT = 8000
STDERR_LIMIT = 4000


async def _resolve_workdir_async(task_path: str, session_id: str) -> Path:
    from app.agent.skills.file_operations.skill import get_tasks_dir

    base = get_tasks_dir()
    if task_path:
        wd = (base / str(task_path)).resolve()
        if str(wd).startswith(str(base.resolve())):
            wd.mkdir(parents=True, exist_ok=True)
            return wd
    if session_id:
        try:
            from app.agent.tools.session_context import get_session_context

            tp = await get_session_context(session_id, "task_path")
            if tp:
                wd = (base / str(tp)).resolve()
                if str(wd).startswith(str(base.resolve())):
                    wd.mkdir(parents=True, exist_ok=True)
                    return wd
        except Exception as e:
            logger.debug(f"[Sandbox] session task_path 解析失败: {e}")
    wd = base / "sandbox"
    wd.mkdir(parents=True, exist_ok=True)
    return wd


class SandboxSkill(BaseSkill):
    """沙箱执行 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "code", "type": "string", "required": False,
         "description": "要执行的 Python 源码（与 file 二选一）"},
        {"name": "file", "type": "string", "required": False,
         "description": "要运行的脚本相对路径，如 test_calculator.py（与 code 二选一）"},
        {"name": "timeout", "type": "integer", "required": False,
         "description": f"超时秒数（默认 {DEFAULT_TIMEOUT}，最大 {MAX_TIMEOUT}）"},
    ]

    def __init__(self):
        super().__init__()
        self.name = "sandbox"
        self.description = "在隔离沙箱中运行 Python 代码或脚本（运行测试/验证），返回 stdout/stderr"
        self.parameters = self.DEFAULT_PARAMETERS

    async def execute(self, **kwargs) -> SkillResult:
        code = (kwargs.get("code") or "").strip()
        file = (kwargs.get("file") or "").strip()
        session_id = kwargs.get("session_id") or ""
        task_path = kwargs.get("task_path") or ""

        try:
            timeout = int(kwargs.get("timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        timeout = max(1, min(timeout, MAX_TIMEOUT))

        if not code and not file:
            return SkillResult(
                success=False,
                error=(
                    "缺少参数：沙箱只收两种参数之一——\n"
                    '  code = 要执行的 Python 源码（"print(1+1)"）\n'
                    '  file = 任务目录内某文件的路径（"app.py"，只写不执行）\n'
                    "不支持 exec/command/shell 等其它参数；服务器未安装 node/npm，"
                    "无法运行 JS/构建命令，请改为用 file 参数写入文件"
                ),
            )

        workdir = await _resolve_workdir_async(task_path, session_id)

        if file:
            # 只允许运行任务目录内的脚本
            script = (workdir / file).resolve()
            if not str(script).startswith(str(workdir.resolve())):
                return SkillResult(success=False, error=f"禁止运行任务目录外的脚本: {file}")
            if not script.exists():
                return SkillResult(success=False, error=f"文件不存在: {file}")
            # -E -s：屏蔽 PYTHON* 环境变量与用户 site，但保留脚本目录入 sys.path
            argv = [sys.executable, "-E", "-s", str(script)]
            friendly = f"运行 {Path(file).name}"
        else:
            argv = [sys.executable, "-I", "-c", code]
            friendly = "运行 Python 代码"

        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/usr/local/bin",
            "HOME": str(workdir),
            "PYTHONIOENCODING": "utf-8",
        }

        def _spawn() -> subprocess.CompletedProcess:
            return subprocess.run(
                argv,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                env=env,
            )

        try:
            proc = await asyncio.to_thread(_spawn)
        except subprocess.TimeoutExpired:
            return SkillResult(
                success=False,
                error=f"timeout: 执行超过 {timeout}s 被终止",
                metadata={"friendly_action": friendly},
            )
        except (OSError, subprocess.SubprocessError) as e:
            return SkillResult(
                success=False,
                error=f"exec_failed: {e}",
                metadata={"friendly_action": friendly},
            )

        stdout = (proc.stdout or "")[-STDOUT_LIMIT:]
        stderr = (proc.stderr or "")[-STDERR_LIMIT:]
        data = {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode,
            "workdir": str(workdir),
            "provider": "restricted",
        }

        if proc.returncode == 0:
            return SkillResult(success=True, data=data, metadata={"friendly_action": friendly})
        return SkillResult(
            success=False,
            data=data,
            error=f"exit_{proc.returncode}: {stderr or '无 stderr 输出'}",
            metadata={"friendly_action": friendly},
        )


# 导出执行入口
skill = SandboxSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
