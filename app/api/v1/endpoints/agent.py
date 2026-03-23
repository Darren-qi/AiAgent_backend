# -*- coding: utf-8 -*-
"""Agent 端点"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime
import asyncio
import json

import logging
logger = logging.getLogger(__name__)

from app.api.deps import OptionalCurrentUser
from app.db.session import get_db
from app.api.v1.schemas.agent import AgentExecuteRequest, AgentExecuteResponse
from app.agent.graphs.main_graph import AgentGraph
from app.agent.memory.manager import MemoryManager
from app.agent.llm.factory import LLMFactory
from app.agent.tools.storage.manager import StorageManager
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard
from app.models.experience import SessionModel

router = APIRouter()

input_guard = InputGuard()
output_guard = OutputGuard()
memory_managers: Dict[str, MemoryManager] = {}
# 会话与任务路径的映射: {session_id: task_folder_name}
session_task_paths: Dict[str, str] = {}


# 会话内存存储（消息数据）
sessions_store: Dict[str, dict] = {}

def _update_session_task_path(session_id: str, task_path: str):
    """更新会话的任务路径（内存 + 数据库）"""
    if session_id in sessions_store:
        sessions_store[session_id]["task_path"] = task_path
        sessions_store[session_id]["updated_at"] = datetime.now().isoformat() + "Z"
    session_task_paths[session_id] = task_path


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: str = "新会话"
    user_input: str = ""
    files: Optional[List[dict]] = None


@router.post("/execute/", response_model=AgentExecuteResponse)
async def execute_task(
    request: AgentExecuteRequest,
    background_tasks: BackgroundTasks,
    user: OptionalCurrentUser = None,
) -> AgentExecuteResponse:
    """执行 Agent 任务"""
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        return AgentExecuteResponse(
            success=False,
            error=error_msg,
            task_id="",
            result={}
        )

    session_id = request.session_id or f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}"
    if session_id not in memory_managers:
        memory_managers[session_id] = MemoryManager(session_id)

    memory_manager = memory_managers[session_id]
    memory_manager.add_user_message(request.task)

    graph = AgentGraph()
    result = await graph.execute(
        task=request.task,
        context={"user_id": user["id"] if user else None, "session_id": session_id}
    )

    if result.get("success"):
        memory_manager.add_assistant_message(str(result.get("result", "")))

    is_safe_output, warning = output_guard.check(str(result.get("result", "")))
    if not is_safe_output:
        result["result"] = output_guard.mask_sensitive(str(result.get("result", "")))

    return AgentExecuteResponse(
        success=result.get("success", False),
        task_id=session_id,
        result=result,
        intent=result.get("intent"),
        warning=warning,
    )


@router.post("/execute/stream")
async def execute_task_stream(
    request: AgentExecuteRequest,
    user: OptionalCurrentUser = None,
) -> StreamingResponse:
    """执行 Agent 任务（流式返回）"""
    # 安全检查
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'message': error_msg})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    session_id = request.session_id or f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}"
    if session_id not in memory_managers:
        memory_managers[session_id] = MemoryManager(session_id)

    memory_manager = memory_managers[session_id]
    memory_manager.add_user_message(request.task)

    # 获取或初始化任务路径
    task_folder = session_task_paths.get(session_id)
    if not task_folder and request.task:
        project_name = _extract_project_name(request.task)
        try:
            from app.agent.tools.storage.manager import StorageManager
            storage = StorageManager()
            task_folder = storage._provider.init_task_path(project_name)
            session_task_paths[session_id] = task_folder
            logger.info(f"[Agent] 初始化任务路径: {task_folder}")
        except Exception as e:
            logger.warning(f"[Agent] 初始化任务路径失败: {e}")
            task_folder = None

    # 定义流式生成器
    async def event_stream():
        # 创建一个队列用于收集事件
        queue = asyncio.Queue()

        # 心跳间隔（秒）
        heartbeat_interval = 30

        # 定义回调函数，将事件添加到队列
        def on_step(step_type: str, data: Dict[str, Any]):
            asyncio.create_task(queue.put(f"event: {step_type}\ndata: {json.dumps(data)}\n\n"))

        # 推送开始事件
        yield f"event: start\ndata: {json.dumps({'task_id': session_id, 'task_path': task_folder})}\n\n"

        # 执行任务（在后台）
        async def execute_task():
            try:
                graph = AgentGraph()
                result = await graph.execute(
                    task=request.task,
                    context={
                        "user_id": user["id"] if user else None,
                        "session_id": session_id,
                        "task_path": task_folder,
                    },
                    on_step=on_step
                )
                # 推送完成事件
                await queue.put(f"event: complete\ndata: {json.dumps(result)}\n\n")

                # 执行完成后，更新会话的任务路径
                if task_folder:
                    _update_session_task_path(session_id, task_folder)
            except Exception as e:
                # 推送错误事件
                await queue.put(f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n")
            finally:
                # 标记任务完成
                await queue.put(None)

        # 启动任务执行
        task = asyncio.create_task(execute_task())

        # 从队列中读取事件并推送，同时发送心跳保持连接
        last_heartbeat = asyncio.get_event_loop().time()

        while True:
            try:
                # 使用超时等待事件，避免永久阻塞
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)

                if event is None:
                    # 任务完成
                    break

                yield event
                last_heartbeat = asyncio.get_event_loop().time()
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                current_time = asyncio.get_event_loop().time()
                if current_time - last_heartbeat >= heartbeat_interval:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': current_time})}\n\n"
                    last_heartbeat = current_time

        # 等待任务完成
        try:
            await task
        except Exception:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


@router.get("/status/{task_id}")
async def get_task_status(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """获取任务状态"""
    return {
        "task_id": task_id,
        "status": "completed",
        "session_id": task_id,
    }


@router.post("/abort/{task_id}")
async def abort_task(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """中止任务"""
    return {
        "task_id": task_id,
        "aborted": True,
    }


# ============ 前端兼容的会话端点 ============

async def _get_db():
    """获取数据库会话，不存在时返回 None（不崩溃）"""
    try:
        async for session in get_db():
            yield session
    except Exception:
        pass


@router.get("/list-sessions/")
async def list_sessions(
    user: OptionalCurrentUser = None,
) -> dict:
    """获取会话列表 - 前端兼容"""
    try:
        from sqlalchemy import select
        async for db in _get_db():
            stmt = select(SessionModel).order_by(SessionModel.updated_at.desc()).limit(50)
            result = await db.execute(stmt)
            sessions_db = result.scalars().all()

            sessions = [
                {
                    "session_id": s.session_id,
                    "title": s.title or "未命名会话",
                    "created_at": s.created_at.isoformat() if s.created_at else "",
                    "updated_at": s.updated_at.isoformat() if s.updated_at else "",
                    "task_path": s.task_path,
                }
                for s in sessions_db
            ]
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "sessions": sessions,
                    "total": len(sessions)
                }
            }
    except Exception:
        pass

    # 降级到内存存储
    sessions = [
        {
            "session_id": sid,
            "title": data.get("title", "未命名会话"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "task_path": data.get("task_path"),
        }
        for sid, data in sessions_store.items()
    ]
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "sessions": sessions,
            "total": len(sessions)
        }
    }


@router.get("/get-session/")
async def get_session(
    session_id: str = Query(..., description="会话ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """获取会话详情 - 前端兼容"""
    file_tree = []
    task_path = None
    session_data = {}

    try:
        async for db in _get_db():
            from sqlalchemy import select
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db.execute(stmt)
            session_db = result.scalar_one_or_none()

            if session_db:
                task_path = session_db.task_path
                if task_path:
                    from app.agent.tools.storage.manager import StorageManager
                    storage = StorageManager()
                    file_tree = await storage.build_file_tree(task_path)
            session_data = sessions_store.get(session_id, {})
            break
    except Exception:
        session_data = sessions_store.get(session_id, {})
        task_path = session_data.get("task_path")

    if not session_data:
        return {
            "code": 0,
            "message": "success",
            "data": {
                "session_id": session_id,
                "messages": [],
                "file_tree": [],
                "task_path": None
            }
        }

    return {
        "code": 0,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": session_data.get("title", ""),
            "messages": session_data.get("messages", []),
            "file_tree": file_tree,
            "task_path": task_path,
        }
    }


@router.post("/create-session/")
async def create_session(
    request: CreateSessionRequest,
    user: OptionalCurrentUser = None,
) -> dict:
    """创建新会话 - 前端兼容"""
    import datetime

    session_id = request.session_id or f"session_{datetime.datetime.now().timestamp()}"
    now = datetime.datetime.now().isoformat() + "Z"

    project_name = None
    if request.user_input:
        project_name = _extract_project_name(request.user_input)

    task_folder = None
    try:
        from app.agent.tools.storage.manager import StorageManager
        storage = StorageManager()
        task_folder = storage._provider.init_task_path(project_name)
    except Exception as e:
        logger.warning(f"[Agent] 初始化任务路径失败: {e}")

    session_data = {
        "session_id": session_id,
        "title": request.title or "新会话",
        "user_input": request.user_input,
        "files": request.files or [],
        "messages": [],
        "file_tree": [],
        "task_path": task_folder,
        "created_at": now,
        "updated_at": now,
    }

    sessions_store[session_id] = session_data
    session_task_paths[session_id] = task_folder

    try:
        async for db in _get_db():
            db_session = SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else 0,
                title=request.title or "新会话",
                status="active",
                task_path=task_folder,
            )
            db.add(db_session)
            await db.commit()
            break
    except Exception as e:
        logger.warning(f"[Agent] 保存会话到数据库失败: {e}")

    return {
        "code": 200,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": request.title or "新会话",
            "created_at": now,
            "task_path": task_folder,
        }
    }


def _extract_project_name(task: str) -> Optional[str]:
    """从任务描述中提取项目名称"""
    import re
    # 尝试匹配 "创建一个 XXX 项目" 或 "生成 XXX 应用" 等模式
    patterns = [
        r'(?:创建|生成|开发|构建|制作)\s*`?([a-zA-Z_][a-zA-Z0-9_]*)',
        r'(?:项目|应用|应用|系统|网站|平台|工具)\s*`?([a-zA-Z_][a-zA-Z0-9_]*)',
        r'`([a-zA-Z_][a-zA-Z0-9_]*(?:_project|_app|_project|_system)?)`',
    ]
    for pattern in patterns:
        match = re.search(pattern, task)
        if match:
            name = match.group(1).strip()
            if len(name) >= 2:
                return name
    return None


@router.delete("/execute/")
async def delete_session_by_query(
    task_id: str = Query(..., description="任务ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """删除会话 - 前端兼容"""
    if task_id in sessions_store:
        del sessions_store[task_id]
    if task_id in session_task_paths:
        del session_task_paths[task_id]

    try:
        async for db in _get_db():
            from sqlalchemy import delete
            stmt = delete(SessionModel).where(SessionModel.session_id == task_id)
            await db.execute(stmt)
            await db.commit()
            break
    except Exception as e:
        logger.warning(f"[Agent] 删除会话失败: {e}")

    return {"success": True, "message": "deleted"}
