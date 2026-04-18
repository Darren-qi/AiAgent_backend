# -*- coding: utf-8 -*-
"""Agent 端点"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncio
import json

from loguru import logger

from app.api.deps import OptionalCurrentUser
from app.db.session import get_db, AsyncSessionLocal
from app.api.v1.schemas.agent import AgentExecuteRequest, AgentExecuteResponse
from app.agent.graphs.main_graph import AgentGraph
from app.agent.memory.manager import MemoryManager
from app.agent.llm.factory import LLMFactory
from app.agent.tools.storage.manager import StorageManager
from app.agent.task_executor import task_manager
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard
from app.models.experience import SessionModel

router = APIRouter()

input_guard = InputGuard()
output_guard = OutputGuard()
# memory_managers 存储 (MemoryManager, AsyncSession) 元组，AsyncSession 需在请求结束时提交
memory_managers: Dict[str, tuple] = {}
# 会话与任务路径的映射: {session_id: task_folder_name}
session_task_paths: Dict[str, str] = {}
# 追踪运行中的任务: {session_id: (asyncio.Task, AgentGraph)}
running_tasks: Dict[str, tuple] = {}


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

    # 注意：括号确保 request.session_id 优先被使用
    session_id = request.session_id or (f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}")
    db = AsyncSessionLocal()

    if session_id not in memory_managers:
        memory_managers[session_id] = (MemoryManager(session_id, db), db)

    _memory_manager, _ = memory_managers[session_id]
    await _memory_manager.add_user_message(request.task)

    # 确保会话在数据库中存在（否则 execution_nodes 外键会失败）
    session_created = False
    try:
        async for db in _get_db():
            from sqlalchemy import select
            from app.models.experience import SessionModel
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                now = datetime.now(timezone.utc)
                db_session = SessionModel(
                    session_id=session_id,
                    user_id=user["id"] if user else 0,
                    title=request.task[:50] if request.task else "新会话",
                    status="active",
                    task_path=None,
                    created_at=now,
                    updated_at=now,
                )
                db.add(db_session)
                await db.commit()
                session_created = True
                logger.info(f"[Agent] 创建数据库会话: {session_id}")
            else:
                logger.debug(f"[Agent] 会话已存在: {session_id}")
            break
    except Exception as e:
        logger.warning(f"[Agent] 创建会话记录失败: {e}")
        # 如果创建失败，尝试从 sessions_store 获取或生成临时会话
        if session_id not in sessions_store:
            sessions_store[session_id] = {
                "session_id": session_id,
                "title": request.task[:50] if request.task else "新会话",
                "messages": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

    graph = AgentGraph()
    result = await graph.execute(
        task=request.task,
        context={"user_id": user["id"] if user else None, "session_id": session_id}
    )

    if result.get("success"):
        await _memory_manager.add_assistant_message(str(result.get("result", "")))
        # 提交数据库会话（保存 conversation_messages）
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"[Agent] 数据库会话提交失败: {e}")

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

    # 记录请求开始
    import sys
    session_id = request.session_id or (f"{user['id']}_{request.task[:20]}" if user else f"anon_{request.task[:20]}")
    sys.stderr.write(f"[Agent] ====== execute/stream: session_id={session_id} ======\n")
    sys.stderr.flush()

    # 创建数据库会话，用于 MemoryManager 和会话记录
    db = AsyncSessionLocal()

    # 确保会话在数据库中存在（否则 execution_nodes 外键会失败）
    session_created = False
    logger.info(f"[Agent] 检查会话是否存在: {session_id}")
    try:
        # 检查会话是否已存在
        from sqlalchemy import select
        from app.models.experience import SessionModel
        stmt = select(SessionModel).where(SessionModel.session_id == session_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if not existing:
            logger.info(f"[Agent] 会话不存在，准备创建: {session_id}")
            task_folder = session_task_paths.get(session_id)
            now = datetime.now(timezone.utc)
            db_session = SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else 0,
                title=request.task[:50] if request.task else "新会话",
                status="active",
                task_path=task_folder,
                created_at=now,
                updated_at=now,
            )
            db.add(db_session)
            await db.commit()
            session_created = True
            logger.info(f"[Agent] 创建数据库会话成功: {session_id}")
        else:
            logger.debug(f"[Agent] 会话已存在: {session_id}")
    except Exception as e:
        import traceback
        logger.error(f"[Agent] 创建会话记录失败: {e}")
        logger.error(f"[Agent] 完整错误: {traceback.format_exc()}")
        # 如果创建失败，尝试从 sessions_store 获取或生成临时会话
        if session_id not in sessions_store:
            sessions_store[session_id] = {
                "session_id": session_id,
                "title": request.task[:50] if request.task else "新会话",
                "messages": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

    # 初始化 MemoryManager，传入数据库会话（这样 conversation_messages 会被保存）
    if session_id not in memory_managers:
        memory_managers[session_id] = (MemoryManager(session_id, db), db)
    else:
        # 已存在的 manager 不再覆盖，保持原样
        pass

    _memory_manager, _ = memory_managers[session_id]
    await _memory_manager.add_user_message(request.task)

    # 任务路径
    task_folder = session_task_paths.get(session_id)
    logger.debug(f"[Agent] 当前会话任务路径: {task_folder}")

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

        # 执行任务
        async def _real_execute_task():
            from app.agent.cancel_signal import cancel_signal

            logger.info(f"[Agent] 任务开始执行: session_id={session_id}")

            # 注册取消信号
            cancel_signal.register(session_id)

            try:
                graph = AgentGraph()
                task_manager.create_task(session_id)
                try:
                    result = await graph.execute(
                        task=request.task,
                        session_id=session_id,
                        task_id=session_id,
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
                finally:
                    # 清理引用
                    task_manager.complete_task(session_id)
                    running_tasks.pop(session_id, None)
                    # 提交数据库会话（保存 conversation_messages 等）
                    try:
                        await db.commit()
                        logger.info(f"[Agent] 数据库会话已提交: session_id={session_id}")
                    except Exception as e:
                        logger.error(f"[Agent] 数据库会话提交失败: {e}")
            except asyncio.CancelledError:
                # 前端断开连接或被 abort 端点取消 — 立即推送 stopped 事件
                logger.warning(f"[Agent] 任务被取消: session_id={session_id}")
                task_manager.stop_task(session_id)
                cancel_signal.cancel(session_id)  # 确保取消信号被设置
                await queue.put(f"event: stopped\ndata: {json.dumps({'message': '任务已被终止'})}\n\n")
                raise
            except Exception as e:
                # 推送错误事件（CancelledError 已在上方被捕获，不会到达此处）
                logger.error(f"[Agent] 任务执行异常: {e}")
                await queue.put(f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n")
                task_manager.fail_task(session_id)
            finally:
                # 注销取消信号
                cancel_signal.unregister(session_id)
                # 标记任务完成
                await queue.put(None)

        # 启动任务执行 - 捕获返回的 task 对象
        task_handle = asyncio.create_task(_real_execute_task())
        # 立即注册到 running_tasks（这样 abort 端点可以立即获取到）
        running_tasks[session_id] = (task_handle, None)

        # 从队列中读取事件并推送，同时发送心跳保持连接
        last_heartbeat = asyncio.get_event_loop().time()

        try:
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
                    # 心跳时也检查中断状态
                    if not task_manager.is_running(session_id):
                        logger.info(f"[Agent] 流循环检测到中断: {session_id}")
                        yield f"event: stopped\ndata: {json.dumps({'message': '任务已被用户中断'})}\n\n"
                        break
        except asyncio.CancelledError:
            # 前端断开连接，取消正在执行的任务
            logger.info(f"[Agent] 前端断开连接，取消任务: {session_id}")
            running_info = running_tasks.pop(session_id, None)
            if running_info:
                running_task, graph = running_info
                # 关键：调用 Task.cancel() 会在最近的 await 点抛出 CancelledError
                # 这会立即中断 LLM 调用等长时间阻塞操作
                if running_task and not running_task.done():
                    running_task.cancel()
                if graph:
                    graph.cancel()
            task_manager.stop_task(session_id)
            raise
        finally:
            # 清理追踪
            running_tasks.pop(session_id, None)

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
        "status": task_manager.get_status(task_id),
        "session_id": task_id,
    }


@router.get("/debug/tasks")
async def debug_tasks() -> Dict[str, Any]:
    """调试端点：查看所有运行中的任务"""
    return {
        "running_tasks_keys": list(running_tasks.keys()),
        "task_manager_all": task_manager.get_all_tasks(),
    }


@router.get("/ping/{task_id}")
async def ping_task(task_id: str) -> Dict[str, Any]:
    """诊断路由：确认 abort 请求是否到达"""
    logger.warning(f"[PING] 收到 ping 请求: {task_id}")
    return {"task_id": task_id, "running_tasks": list(running_tasks.keys())}


@router.post("/abort/{task_id}")
async def abort_task(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """中止任务"""
    import logging
    from app.agent.cancel_signal import cancel_signal

    logger.info(f"[ABORT] 收到 abort 请求: {task_id}")

    # 1. 通过 CancelSignal 发送取消信号（让 LLM 调用能立即感知）
    cancel_signal.cancel(task_id)

    # 2. 通过 TaskManager 停止（设置状态，但不中断 await）
    stopped = task_manager.stop_task(task_id)

    # 3. 通过 running_tasks 取消 asyncio Task — 这是真正中断 await 的机制
    running_info = running_tasks.pop(task_id, None)
    if running_info:
        running_task, graph = running_info
        # 关键：调用 Task.cancel() 会在最近的 await 点抛出 CancelledError
        if running_task:
            running_task.cancel()
        if graph:
            graph.cancel()

    return {
        "success": True,
        "task_id": task_id,
        "stopped": stopped,
        "cancelled": running_info is not None,
    }

    logger.warning(f"[ABORT] ====== abort 完成: {task_id}, task_manager={stopped} ======")
    return {"task_id": task_id, "aborted": True, "cancelled": True}


# ============ 前端兼容的会话端点 ============

async def _get_db():
    """获取数据库会话，不存在时返回 None（不崩溃）"""
    try:
        async for session in get_db():
            yield session
    except Exception as e:
        logger.error(f"[Agent] 数据库会话获取失败: {e}")


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
                    "task_path": None,  # task_path 存储在 SessionContext 表中
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
                # 从 SessionContext 表获取 task_path
                task_path = None
                try:
                    from app.agent.tools.session_context import get_session_context
                    task_path = await get_session_context(session_id, "task_path")
                except Exception:
                    pass
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

    # 注意：不在 create-session 时创建任务目录
    # 任务目录在 execute/stream 首次执行时才创建（带时间戳），后续复用同一目录
    # 这样确保每个会话只有一个任务目录，避免多次创建带不同时间戳的目录
    task_folder = None

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
            now = datetime.now(timezone.utc)
            db_session = SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else 0,
                title=request.title or "新会话",
                status="active",
                task_path=task_folder,
                created_at=now,
                updated_at=now,
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
