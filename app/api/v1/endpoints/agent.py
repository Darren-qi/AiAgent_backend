# -*- coding: utf-8 -*-
"""Agent 端点 — AutoGen 版"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncio
import json
import os
import zipfile
import io

from loguru import logger

from app.api.deps import OptionalCurrentUser
from app.db.session import get_db, AsyncSessionLocal
from app.api.v1.schemas.agent import AgentExecuteRequest, AgentExecuteResponse
from app.agent.autogen.session_manager import session_manager
from app.agent.autogen.stream_adapter import SSEStreamAdapter
from app.agent.autogen.tools.skill_bridge import file_read, file_list
from app.agent.task_executor import task_manager
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard
from app.models.experience import SessionModel

router = APIRouter()

input_guard = InputGuard()
output_guard = OutputGuard()

# 内存存储（降级用）
sessions_store: Dict[str, dict] = {}
# 运行中任务追踪：{session_id: asyncio.Task}
running_tasks: Dict[str, asyncio.Task] = {}


# ── 请求模型 ──────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: str = "新会话"
    user_input: str = ""
    files: Optional[List[dict]] = None


# ── 数据库辅助 ────────────────────────────────────────────

async def _get_db():
    """获取数据库会话，失败时静默跳过"""
    try:
        async for session in get_db():
            yield session
    except Exception as e:
        logger.error(f"[Agent] 数据库会话获取失败: {e}")


async def _ensure_session_in_db(session_id: str, title: str, user_id: Optional[int], db) -> bool:
    """确保会话记录存在于数据库，返回是否新建"""
    try:
        from sqlalchemy import select
        stmt = select(SessionModel).where(SessionModel.session_id == session_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if not existing:
            now = datetime.now(timezone.utc)
            db.add(SessionModel(
                session_id=session_id,
                user_id=user_id,
                title=title[:50] if title else None,
                status="active",
                created_at=now,
                updated_at=now,
            ))
            await db.commit()
            return True
    except Exception as e:
        logger.warning(f"[Agent] 确保会话记录失败: {e}")
    return False


# ── 同步执行端点 ──────────────────────────────────────────

@router.post("/execute/", response_model=AgentExecuteResponse)
async def execute_task(
    request: AgentExecuteRequest,
    user: OptionalCurrentUser = None,
) -> AgentExecuteResponse:
    """执行 Agent 任务（非流式）"""
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        return AgentExecuteResponse(success=False, error=error_msg, task_id="", result={})

    session_id = request.session_id or (
        f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}"
    )
    db = AsyncSessionLocal()
    await _ensure_session_in_db(
        session_id, request.task, user["id"] if user else 0, db
    )

    events: List[Dict] = []

    def on_event(event_type: str, data: Dict[str, Any]):
        events.append({"type": event_type, "data": data})

    try:
        result = await session_manager.execute(
            session_id=session_id,
            task=request.task,
            context={"user_id": user["id"] if user else None},
            on_event=on_event,
            db_session=db,
        )
    except Exception as e:
        logger.error(f"[Agent] 执行失败: {e}")
        return AgentExecuteResponse(success=False, error=str(e), task_id=session_id, result={})
    finally:
        try:
            await db.commit()
        except Exception:
            pass

    summary = result.get("summary", "")
    is_safe_out, warning = output_guard.check(summary)
    if not is_safe_out:
        summary = output_guard.mask_sensitive(summary)

    return AgentExecuteResponse(
        success=result.get("success", False),
        task_id=session_id,
        result=result,
        warning=warning,
    )


# ── 流式执行端点 ──────────────────────────────────────────

@router.post("/execute/stream")
async def execute_task_stream(
    request: AgentExecuteRequest,
    user: OptionalCurrentUser = None,
) -> StreamingResponse:
    """执行 Agent 任务（SSE 流式）"""
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        async def _err():
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': error_msg}}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    session_id = request.session_id or (
        f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}"
    )
    logger.info(f"[Agent] execute/stream: session_id={session_id}")

    # 初始化会话存储（用于消息持久化）
    now_str = datetime.now().isoformat() + "Z"
    if session_id not in sessions_store:
        sessions_store[session_id] = {
            "session_id": session_id,
            "title": request.task[:50] + ("..." if len(request.task) > 50 else ""),
            "messages": [],
            "file_tree": [],
            "task_path": None,
            "created_at": now_str,
            "updated_at": now_str,
        }
    if "messages" not in sessions_store[session_id]:
        sessions_store[session_id]["messages"] = []

    db = AsyncSessionLocal()
    await _ensure_session_in_db(
        session_id, request.task, user["id"] if user else 0, db
    )

    adapter = SSEStreamAdapter()

    def _on_event_with_persist(event_type: str, data: Dict[str, Any]):
        """包装回调，在转发事件的同时持久化消息"""
        # 先转发给 SSE 适配器
        adapter.on_event(event_type, data)

        # 持久化消息到 sessions_store
        store = sessions_store.get(session_id)
        if store is None:
            return

        if event_type == "agent_message":
            store["messages"].append({
                "type": "assistant",
                "content": data.get("full_content", data.get("content", "")),
                "_agent": data.get("agent"),
                "_avatar": data.get("avatar"),
                "_color": data.get("color"),
                "_display_name": data.get("display_name"),
                "_collapsed": True,
            })
            store["updated_at"] = datetime.now().isoformat() + "Z"

        elif event_type in ("done", "complete", "error", "stopped"):
            msg = data.get("result", data.get("message", data.get("summary", "")))
            if msg:
                store["messages"].append({
                    "type": "assistant",
                    "content": msg,
                })
                store["updated_at"] = datetime.now().isoformat() + "Z"

    # 先保存用户消息
    if request.task:
        sessions_store[session_id]["messages"].append({
            "type": "user",
            "content": request.task,
        })

    async def _run_team():
        """后台执行 AutoGen 团队，结束后关闭适配器"""
        try:
            task_manager.create_task(session_id)
            await session_manager.execute(
                session_id=session_id,
                task=request.task,
                context={"user_id": user["id"] if user else None},
                on_event=_on_event_with_persist,
                db_session=db,
            )
        except asyncio.CancelledError:
            logger.warning(f"[Agent] 任务被取消: {session_id}")
            adapter.on_event("stopped", {"message": "任务已被用户中断"})
            raise
        except Exception as e:
            logger.error(f"[Agent] 团队执行异常: {e}")
            adapter.on_event("error", {"message": str(e)})
        finally:
            task_manager.complete_task(session_id)
            running_tasks.pop(session_id, None)
            try:
                await db.commit()
            except Exception:
                pass
            adapter.close()

    async def event_stream():
        # 推送开始事件
        yield f"data: {json.dumps({'type': 'start', 'data': {'task_id': session_id}}, ensure_ascii=False)}\n\n"

        # 启动后台团队任务
        task_handle = asyncio.create_task(_run_team())
        running_tasks[session_id] = task_handle

        try:
            async for sse_line in adapter.stream():
                yield sse_line
        except asyncio.CancelledError:
            logger.info(f"[Agent] 前端断开: {session_id}")
            t = running_tasks.pop(session_id, None)
            if t and not t.done():
                t.cancel()
            task_manager.stop_task(session_id)
            raise
        finally:
            running_tasks.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 任务控制端点 ──────────────────────────────────────────

@router.get("/status/{task_id}")
async def get_task_status(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """获取任务状态"""
    return {
        "task_id": task_id,
        "status": task_manager.get_status(task_id),
        "session_id": task_id,
    }


@router.post("/abort/{task_id}")
async def abort_task(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """中止任务"""
    logger.info(f"[ABORT] 收到 abort 请求: {task_id}")

    # 通知 AutoGen 团队中止
    aborted = await session_manager.abort(task_id)

    # 取消 asyncio Task
    t = running_tasks.pop(task_id, None)
    if t and not t.done():
        t.cancel()

    task_manager.stop_task(task_id)

    return {
        "success": True,
        "task_id": task_id,
        "aborted": aborted,
    }


@router.get("/debug/tasks")
async def debug_tasks() -> Dict[str, Any]:
    """调试：查看运行中任务"""
    return {
        "running_tasks": list(running_tasks.keys()),
        "task_manager_all": task_manager.get_all_tasks(),
    }


# ── 会话管理端点 ──────────────────────────────────────────

@router.get("/list-sessions/")
async def list_sessions(user: OptionalCurrentUser = None) -> dict:
    """获取会话列表"""
    try:
        from sqlalchemy import select
        async for db in _get_db():
            stmt = select(SessionModel).order_by(SessionModel.updated_at.desc()).limit(50)
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "sessions": [
                        {
                            "session_id": s.session_id,
                            "title": s.title or "未命名会话",
                            "created_at": s.created_at.isoformat() if s.created_at else "",
                            "updated_at": s.updated_at.isoformat() if s.updated_at else "",
                            "task_path": None,
                        }
                        for s in rows
                    ],
                    "total": len(rows),
                },
            }
    except Exception as e:
        logger.error(f"[Agent] list-sessions 失败: {e}")

    # 降级：内存存储
    sessions = sorted(sessions_store.values(), key=lambda x: x.get("updated_at", ""), reverse=True)
    return {
        "code": 200,
        "message": "success",
        "data": {"sessions": sessions[:50], "total": len(sessions)},
    }


@router.get("/get-session/")
async def get_session(
    session_id: str = Query(..., description="会话ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """获取会话详情"""
    try:
        from sqlalchemy import select
        async for db in _get_db():
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                # 尝试从 sessions_store 获取消息（内存中的最新数据）
                store_data = sessions_store.get(session_id, {})
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "session_id": row.session_id,
                        "title": row.title or "",
                        "messages": store_data.get("messages", []),
                        "file_tree": [],
                        "task_path": row.task_path,
                    },
                }
    except Exception as e:
        logger.error(f"[Agent] get-session 失败: {e}")

    data = sessions_store.get(session_id, {})
    return {
        "code": 0,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": data.get("title", ""),
            "messages": data.get("messages", []),
            "file_tree": [],
            "task_path": data.get("task_path"),
        },
    }


@router.post("/create-session/")
async def create_session(
    request: CreateSessionRequest,
    user: OptionalCurrentUser = None,
) -> dict:
    """创建新会话"""
    session_id = request.session_id or f"session_{datetime.now().timestamp()}"
    now_str = datetime.now().isoformat() + "Z"

    sessions_store[session_id] = {
        "session_id": session_id,
        "title": request.title or "新会话",
        "messages": [],
        "file_tree": [],
        "task_path": None,
        "created_at": now_str,
        "updated_at": now_str,
    }

    try:
        async for db in _get_db():
            now = datetime.now(timezone.utc)
            db.add(SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else None,
                title=request.title or "新会话",
                status="active",
                created_at=now,
                updated_at=now,
            ))
            await db.commit()
            break
    except Exception as e:
        logger.warning(f"[Agent] 保存会话失败: {e}")

    return {
        "code": 200,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": request.title or "新会话",
            "created_at": now_str,
            "task_path": None,
        },
    }

@router.get("/read-file/")
async def read_file(
    file_path: str = Query(..., description="文件路径"),
    session_id: Optional[str] = Query(None, description="会话ID"),
) -> dict:
    """读取文件内容"""
    try:
        result_str = await file_read(
            path=file_path,
            task_path=None,
            session_id=session_id,
        )
        logger.info(f"[read_file] result_str type: {type(result_str)}, starts: {repr(result_str[:50])}")
        # file_read 返回的是字符串（可能是 JSON 字符串或纯文本）
        # 尝试解析为 JSON
        try:
            import json
            result_data = json.loads(result_str)
            # 如果是 JSON 且包含 success 字段，按原逻辑处理
            if isinstance(result_data, dict) and "success" in result_data:
                if result_data.get("success"):
                    return {
                        "code": 0,
                        "message": "success",
                        "data": result_data.get("data", ""),
                    }
                else:
                    return {
                        "code": 500,
                        "message": result_data.get("error", "读取文件失败"),
                        "data": None,
                    }
            # 如果是 JSON 但没有 success 字段，检查是否有 content 字段（新格式）
            if isinstance(result_data, dict) and "content" in result_data:
                return {
                    "code": 0,
                    "message": "success",
                    "data": result_data.get("content", ""),
                }
            # 其他 JSON 结构，直接返回整个 JSON 作为 data
            return {
                "code": 0,
                "message": "success",
                "data": result_str,  # 保持原 JSON 字符串
            }
        except json.JSONDecodeError:
            # 不是 JSON，直接作为文件内容返回
            return {
                "code": 0,
                "message": "success",
                "data": result_str,
            }
    except Exception as e:
        logger.error(f"[Agent] 读取文件失败: {e}")
        return {
            "code": 500,
            "message": str(e),
            "data": None,
        }

@router.get("/get-files/")
async def get_files(
    session_id: str = Query(..., description="会话ID"),
) -> dict:
    """获取会话文件列表"""
    try:
        files = []

        # 1. 从 .agent_workspace/{session_id}/ 获取文件
        workspace_path = os.path.join(AGENT_WORKSPACE, session_id)
        if os.path.exists(workspace_path):
            for root, dirs, filenames in os.walk(workspace_path):
                for filename in filenames:
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, workspace_path)
                    stat = os.stat(full_path)
                    files.append({
                        "name": filename,
                        "path": rel_path,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "type": "workspace"
                    })

        # 2. 从 tasks/ 目录获取文件（根据 session_id 匹配项目目录）
        # 优先精确匹配 session_id，如果不存在则使用前缀匹配
        tasks_base = os.path.abspath(AGENT_TASKS_DIR)
        target_dir = None

        if os.path.exists(tasks_base):
            # 首先尝试精确匹配
            exact_path = os.path.join(tasks_base, session_id)
            if os.path.isdir(exact_path):
                target_dir = session_id
            else:
                # 前缀匹配 - 查找以 session_id 开头的目录
                # 为了避免匹配太多，使用更精确的匹配（至少前15个字符）
                prefix = session_id[:15] if len(session_id) >= 15 else session_id
                for item in os.listdir(tasks_base):
                    if item.startswith(prefix):
                        target_dir = item
                        break

            # 获取目标目录的文件
            if target_dir:
                target_path = os.path.join(tasks_base, target_dir)
                for root, dirs, filenames in os.walk(target_path):
                    for filename in filenames:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, target_path)
                        stat = os.stat(full_path)
                        files.append({
                            "name": filename,
                            "path": os.path.join(target_dir, rel_path),
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "type": "task"
                        })

        return {
            "code": 0,
            "message": "success",
            "data": {"files": files},
        }
    except Exception as e:
        logger.error(f"[Agent] 获取文件列表失败: {e}")
        return {
            "code": 500,
            "message": str(e),
            "data": None,
        }


# 工作目录
AGENT_WORKSPACE = ".agent_workspace"
# Agent生成的项目保存目录
AGENT_TASKS_DIR = "../tasks"


@router.get("/download-file/")
async def download_file(
    file_path: str = Query(..., description="文件路径"),
    session_id: str = Query(..., description="会话ID"),
) -> StreamingResponse:
    """下载单个文件"""
    try:
        # 优先从 .agent_workspace 查找
        workspace_path = os.path.join(AGENT_WORKSPACE, session_id, file_path)
        full_path = os.path.abspath(workspace_path)

        # 如果文件不存在，尝试从 tasks 目录查找
        if not os.path.exists(full_path):
            tasks_path = os.path.join(AGENT_TASKS_DIR, file_path)
            full_path = os.path.abspath(tasks_path)

        # 安全检查：防止路径遍历
        workspace_abs = os.path.abspath(AGENT_WORKSPACE)
        tasks_abs = os.path.abspath(AGENT_TASKS_DIR)
        if not (full_path.startswith(workspace_abs) or full_path.startswith(tasks_abs)):
            return StreamingResponse(
                content=iter([b"Invalid path"]),
                status_code=400,
                media_type="text/plain"
            )

        if not os.path.exists(full_path):
            return StreamingResponse(
                content=iter([b"File not found"]),
                status_code=404,
                media_type="text/plain"
            )

        # 获取文件名
        filename = os.path.basename(full_path)

        return FileResponse(
            path=full_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    except Exception as e:
        logger.error(f"[Agent] 下载文件失败: {e}")
        return StreamingResponse(
            content=iter([str(e).encode()]),
            status_code=500,
            media_type="text/plain"
        )


@router.get("/download-dir/")
async def download_dir(
    dir: str = Query(..., description="目录名"),
) -> StreamingResponse:
    """下载整个目录（ZIP格式）"""
    try:
        # 优先从 .agent_workspace 查找
        dir_path = os.path.join(AGENT_WORKSPACE, dir)
        dir_path = os.path.abspath(dir_path)

        # 如果目录不存在，尝试从 tasks 目录查找
        if not os.path.exists(dir_path):
            tasks_path = os.path.join(AGENT_TASKS_DIR, dir)
            dir_path = os.path.abspath(tasks_path)

        # 安全检查
        workspace_abs = os.path.abspath(AGENT_WORKSPACE)
        tasks_abs = os.path.abspath(AGENT_TASKS_DIR)
        if not (dir_path.startswith(workspace_abs) or dir_path.startswith(tasks_abs)):
            return StreamingResponse(
                content=iter([b"Invalid path"]),
                status_code=400,
                media_type="text/plain"
            )

        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            return StreamingResponse(
                content=iter([b"Directory not found"]),
                status_code=404,
                media_type="text/plain"
            )

        # 创建ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, dir_path)
                    zf.write(file_path, arcname)

        zip_buffer.seek(0)

        return StreamingResponse(
            content=iter([zip_buffer.getvalue()]),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={dir}.zip"}
        )
    except Exception as e:
        logger.error(f"[Agent] 下载目录失败: {e}")
        return StreamingResponse(
            content=iter([str(e).encode()]),
            status_code=500,
            media_type="text/plain"
        )



@router.put("/session/rename/")
async def rename_session(
    session_id: str = Query(..., description="会话ID"),
    title: str = Query(..., description="新标题"),
    user: OptionalCurrentUser = None,
) -> dict:
    """重命名会话"""
    # 更新内存存储
    if session_id in sessions_store:
        sessions_store[session_id]["title"] = title
        sessions_store[session_id]["updated_at"] = datetime.now().isoformat() + "Z"

    # 更新数据库
    try:
        async for db in _get_db():
            await db.execute(
                update(SessionModel)
                .where(SessionModel.session_id == session_id)
                .values(title=title)
            )
            await db.commit()
            break
    except Exception as e:
        logger.warning(f"[Agent] 重命名会话失败: {e}")

    return {"success": True, "message": "renamed", "title": title}


@router.delete("/execute/")
async def delete_session(
    task_id: str = Query(..., description="任务ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """删除会话"""
    sessions_store.pop(task_id, None)
    session_manager.remove_session(task_id)

    try:
        async for db in _get_db():
            from sqlalchemy import delete, update
            await db.execute(delete(SessionModel).where(SessionModel.session_id == task_id))
            await db.commit()
            break
    except Exception as e:
        logger.warning(f"[Agent] 删除会话失败: {e}")

    return {"success": True, "message": "deleted"}
