# -*- coding: utf-8 -*-
"""Agent 端点"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from pydantic import BaseModel
from datetime import datetime

from app.api.deps import DBSession, OptionalCurrentUser
from app.api.v1.schemas.agent import AgentExecuteRequest, AgentExecuteResponse
from app.agent.graphs.main_graph import AgentGraph
from app.agent.memory.manager import MemoryManager
from app.agent.llm.factory import LLMFactory
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard

router = APIRouter()

input_guard = InputGuard()
output_guard = OutputGuard()
memory_managers: Dict[str, MemoryManager] = {}

# 内存会话存储
sessions_store: Dict[str, dict] = {}


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

@router.get("/list-sessions/")
async def list_sessions(user: OptionalCurrentUser = None) -> dict:
    """获取会话列表 - 前端兼容"""
    sessions = [
        {
            "session_id": sid,
            "title": data.get("title", "未命名会话"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }
        for sid, data in sessions_store.items()
    ]
    # 按更新时间排序
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
    if session_id not in sessions_store:
        return {
            "code": 0,
            "message": "success",
            "data": {
                "session_id": session_id,
                "messages": [],
                "file_tree": []
            }
        }

    session_data = sessions_store[session_id]
    return {
        "code": 0,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": session_data.get("title", ""),
            "messages": session_data.get("messages", []),
            "file_tree": session_data.get("file_tree", [])
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

    session_data = {
        "session_id": session_id,
        "title": request.title or "新会话",
        "user_input": request.user_input,
        "files": request.files or [],
        "messages": [],
        "file_tree": [],
        "created_at": now,
        "updated_at": now,
    }

    sessions_store[session_id] = session_data

    return {
        "code": 200,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": request.title or "新会话",
            "created_at": now
        }
    }


@router.delete("/execute/")
async def delete_session_by_query(
    task_id: str = Query(..., description="任务ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """删除会话 - 前端兼容"""
    if task_id in sessions_store:
        del sessions_store[task_id]
    return {"success": True, "message": "deleted"}
