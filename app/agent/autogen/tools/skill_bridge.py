# -*- coding: utf-8 -*-
"""将现有 Skills 包装为 AutoGen 可调用的工具函数"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def _run_skill(name: str, **kwargs) -> str:
    from app.agent.skills.core.progressive_loader import get_loader
    loader = get_loader()
    result = await loader.execute(name, kwargs)
    if result.success:
        # 如果 data 是字典，返回 JSON 字符串以便解析
        if isinstance(result.data, dict):
            import json
            return json.dumps(result.data, ensure_ascii=False)
        return str(result.data)
    return f"[ERROR] {result.error}"


# ── 文件操作 ──────────────────────────────────────────────
async def file_write(path: str, content: str, task_path: str = "", session_id: str = "") -> str:
    """写入文件。path: 相对于项目根目录的路径；content: 文件内容"""
    return await _run_skill("file_operations", operation="write", path=path,
                            content=content, task_path=task_path, session_id=session_id)


async def file_read(path: str, task_path: str = "", session_id: str = "") -> str:
    """读取文件内容"""
    return await _run_skill("file_operations", operation="read", path=path,
                            task_path=task_path, session_id=session_id)


async def file_list(path: str = "") -> str:
    """列出目录内容"""
    return await _run_skill("file_operations", operation="list", path=path)


async def project_create(project_name: str, session_id: str = "") -> str:
    """创建项目目录，返回带时间戳的项目文件夹名"""
    return await _run_skill("file_operations", operation="create",
                            path=project_name, session_id=session_id)


# ── 代码生成 ──────────────────────────────────────────────
async def code_generate(requirements: str, language: str = "python",
                        framework: str = "", task_path: str = "", session_id: str = "") -> str:
    """根据需求生成代码"""
    return await _run_skill("code_generator", requirements=requirements,
                            language=language, framework=framework,
                            task_path=task_path, session_id=session_id)


# ── HTTP 请求 ─────────────────────────────────────────────
async def http_request(url: str, method: str = "GET",
                       headers: Dict[str, str] = None, body: str = "") -> str:
    """发送 HTTP 请求"""
    return await _run_skill("http_client", url=url, method=method,
                            headers=headers or {}, body=body)


# ── 搜索 ──────────────────────────────────────────────────
async def web_search(query: str) -> str:
    """搜索网络信息"""
    return await _run_skill("search", query=query)


# ── 数据处理 ──────────────────────────────────────────────
async def data_process(data: str, operation: str, params: str = "") -> str:
    """处理和转换数据"""
    return await _run_skill("data_processor", data=data, operation=operation, params=params)


# ── 产物写入（阶段文档）────────────────────────────────────
async def write_artifact(stage: str, content: str, session_id: str,
                         workspace: str) -> str:
    """
    将阶段性产物写入 .agent_workspace/{session_id}/ 目录。
    stage: requirements | architecture | ui_design | api_spec | test_report | acceptance
    """
    import os
    from pathlib import Path

    stage_files = {
        "requirements": "01_requirements.md",
        "architecture": "02_architecture.md",
        "ui_design":    "03_ui_design.md",
        "api_spec":     "04_api_spec.md",
        "test_report":  "05_test_report.md",
        "acceptance":   "07_acceptance.md",
    }
    filename = stage_files.get(stage, f"{stage}.md")

    out_dir = Path(workspace) / session_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 迭代版本：若文件已存在则追加版本号
    target = out_dir / filename
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        version = 2
        while (out_dir / f"{stem}_v{version}{suffix}").exists():
            version += 1
        target = out_dir / f"{stem}_v{version}{suffix}"
        filename = target.name

    target.write_text(content, encoding="utf-8")
    logger.info(f"[Artifact] 写入产物: {target}")
    return str(target)


# ── 工具注册表（按角色/任务类型分组）────────────────────────
TOOL_REGISTRY: Dict[str, Any] = {
    "file_write":     file_write,
    "file_read":      file_read,
    "file_list":      file_list,
    "project_create": project_create,
    "code_generate":  code_generate,
    "http_request":   http_request,
    "web_search":     web_search,
    "data_process":   data_process,
    "write_artifact": write_artifact,
}

# 按任务类型推荐的工具子集（避免全量注入）
TASK_TOOL_GROUPS: Dict[str, list] = {
    "code":    ["project_create", "file_write", "file_read", "file_list", "code_generate", "write_artifact"],
    "web":     ["http_request", "web_search", "file_write", "write_artifact"],
    "data":    ["data_process", "file_read", "file_write", "write_artifact"],
    "general": ["file_write", "file_read", "web_search", "write_artifact"],
}


def get_tools_for_task(task_type: str) -> Dict[str, Any]:
    """根据任务类型返回需要注册的工具子集"""
    keys = TASK_TOOL_GROUPS.get(task_type, TASK_TOOL_GROUPS["general"])
    return {k: TOOL_REGISTRY[k] for k in keys if k in TOOL_REGISTRY}
