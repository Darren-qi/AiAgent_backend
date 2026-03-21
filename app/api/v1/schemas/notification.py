"""Notification Schema"""

from typing import List, Optional
from pydantic import BaseModel, Field


class NotificationSendRequest(BaseModel):
    """通知发送请求"""
    channel: str = Field(..., description="渠道: email, feishu, wecom, dingtalk, telegram")
    recipients: List[str] = Field(..., description="接收者列表")
    subject: str = Field(..., description="主题")
    content: str = Field(..., description="内容")
    html: bool = Field(False, description="是否为 HTML 格式")
    attachments: Optional[List[dict]] = Field(None, description="附件列表")


class NotificationSendResponse(BaseModel):
    """通知发送响应"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
