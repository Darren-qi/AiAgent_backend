"""Social Schema"""

from typing import List, Optional
from pydantic import BaseModel, Field


class SocialSendRequest(BaseModel):
    """社交发送请求"""
    provider: str = Field(..., description="平台: feishu, wecom, dingtalk, telegram")
    chat_id: str = Field(..., description="聊天 ID")
    content: str = Field(..., description="消息内容")
    msg_type: str = Field("text", description="消息类型: text, image, markdown")


class SocialSendResponse(BaseModel):
    """社交发送响应"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
