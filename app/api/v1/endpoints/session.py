# -*- coding: utf-8 -*-
"""Session 端点"""

from typing import Optional, List
from fastapi import APIRouter, Query, HTTPException, status
from pydantic import BaseModel

from app.api.deps import DBSession, CurrentUser
from app.api.v1.schemas.session import SessionResponse, SessionListResponse

router = APIRouter()

# 内存存储会话（实际项目中应该用数据库）
sessions_store = {}


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: str = "新会话"
    user_input: str = ""
    files: Optional[List[dict]] = None


@router.get("/list-sessions/", response_model=List[SessionResponse])
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = None,
) -> List[SessionResponse]:
    """获取会话列表 - 前端兼容"""
    sessions = list(sessions_store.values())[offset:offset+limit]
    if not sessions:
        return []
    return [
        SessionResponse(
            session_id=s.get("session_id", ""),
            user_id=str(user["id"]) if user else "0",
            messages=s.get("messages", []),
            created_at=s.get("created_at", "2024-01-01T00:00:00Z"),
            updated_at=s.get("updated_at", "2024-01-01T00:00:00Z"),
        )
        for s in sessions
    ]


@router.get("/get-session/", response_model=SessionResponse)
async def get_session_by_query(
    session_id: str = Query(..., description="会话ID"),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = None,
) -> SessionResponse:
    """通过查询参数获取会话 - 前端兼容"""
    if session_id not in sessions_store:
        return SessionResponse(
            session_id=session_id,
            user_id=str(user["id"]) if user else "0",
            messages=[],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    
    s = sessions_store[session_id]
    return SessionResponse(
        session_id=s.get("session_id", ""),
        user_id=str(user["id"]) if user else "0",
        messages=s.get("messages", []),
        created_at=s.get("created_at", "2024-01-01T00:00:00Z"),
        updated_at=s.get("updated_at", "2024-01-01T00:00:00Z"),
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = None,
) -> SessionResponse:
    """获取会话详情"""
    if session_id not in sessions_store:
        return SessionResponse(
            session_id=session_id,
            user_id=str(user["id"]) if user else "0",
            messages=[],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
    
    s = sessions_store[session_id]
    return SessionResponse(
        session_id=s.get("session_id", ""),
        user_id=str(user["id"]) if user else "0",
        messages=s.get("messages", []),
        created_at=s.get("created_at", "2024-01-01T00:00:00Z"),
        updated_at=s.get("updated_at", "2024-01-01T00:00:00Z"),
    )


@router.post("/create-session/", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    user: CurrentUser = None,
) -> SessionResponse:
    """创建新会话"""
    import datetime
    
    session_id = request.session_id or f"session_{datetime.datetime.now().timestamp()}"
    now = datetime.datetime.now().isoformat() + "Z"
    
    session_data = {
        "session_id": session_id,
        "title": request.title,
        "user_input": request.user_input,
        "files": request.files or [],
        "messages": [],
        "created_at": now,
        "updated_at": now,
    }
    
    sessions_store[session_id] = session_data
    
    return SessionResponse(
        session_id=session_id,
        user_id=str(user["id"]) if user else "0",
        messages=[],
        created_at=now,
        updated_at=now,
    )


@router.get("/", response_model=List[SessionResponse])
async def list_sessions_path(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: CurrentUser = None,
) -> List[SessionResponse]:
    """获取会话列表"""
    return await list_sessions(limit, offset, user)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user: CurrentUser = None,
) -> dict:
    """删除会话"""
    if session_id in sessions_store:
        del sessions_store[session_id]
    return {"deleted": True, "session_id": session_id}
