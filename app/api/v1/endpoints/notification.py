# -*- coding: utf-8 -*-
"""Notification 端点"""

from typing import List, Optional
from fastapi import APIRouter

from app.api.deps import DBSession, CurrentUser
from app.api.v1.schemas.notification import NotificationSendRequest, NotificationSendResponse
from app.agent.tools.notification.manager import NotificationManager

router = APIRouter()
notification_manager = NotificationManager()


@router.post("/send", response_model=NotificationSendResponse)
async def send_notification(
    request: NotificationSendRequest,
    user: CurrentUser = None,
) -> NotificationSendResponse:
    """发送通知"""
    if request.channel == "email":
        result = await notification_manager.send_email(
            to=request.recipients,
            subject=request.subject,
            content=request.content,
            html=request.html,
        )
    else:
        result = await notification_manager.send_to_social(
            provider=request.channel,
            chat_id=request.recipients[0] if request.recipients else "",
            content=f"{request.subject}\n\n{request.content}",
        )

    return NotificationSendResponse(
        success=result.success,
        message_id=result.message_id,
        error=result.error,
    )


@router.post("/broadcast")
async def broadcast_notification(
    channels: List[str],
    recipients: dict,
    subject: str,
    content: str,
    user: CurrentUser = None,
) -> dict:
    """广播通知"""
    results = await notification_manager.send_broadcast(
        channels=channels,
        recipients=recipients,
        subject=subject,
        content=content,
    )
    return {"results": results}


@router.post("/scheduled")
async def send_scheduled_notification(
    task_name: str,
    status: str,
    result: str,
    channels: List[str],
    user: CurrentUser = None,
) -> dict:
    """发送定时任务通知"""
    results = await notification_manager.send_scheduled_notification(
        task_name=task_name,
        status=status,
        result=result,
        notify_channels=channels,
    )
    return {"results": results}
