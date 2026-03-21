"""Session Schema"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class Message(BaseModel):
    """消息"""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    user_id: str
    messages: List[Dict[str, Any]]
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionResponse]
    total: int
