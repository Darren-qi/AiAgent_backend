# -*- coding: utf-8 -*-
"""Social 端点"""

from typing import List
from fastapi import APIRouter

from app.api.deps import DBSession, CurrentUser
from app.api.v1.schemas.social import SocialSendRequest, SocialSendResponse
from app.agent.tools.social.manager import SocialManager

router = APIRouter()
social_manager = SocialManager()


@router.post("/send", response_model=SocialSendResponse)
async def send_message(
    request: SocialSendRequest,
    user: CurrentUser = None,
) -> SocialSendResponse:
    """发送社交平台消息"""
    result = await social_manager.send_message(
        provider=request.provider,
        chat_id=request.chat_id,
        content=request.content,
        msg_type=request.msg_type,
    )

    return SocialSendResponse(
        success=result.success,
        message_id=result.message_id,
        error=result.error,
    )


@router.get("/providers")
async def list_providers(user: CurrentUser = None) -> dict:
    """获取已配置的社交平台"""
    providers = social_manager.get_available_providers()
    return {"providers": providers}


@router.post("/send_image")
async def send_image(
    provider: str,
    chat_id: str,
    image_url: str,
    user: CurrentUser = None,
) -> dict:
    """发送图片"""
    result = await social_manager.send_image(
        provider=provider,
        chat_id=chat_id,
        image_url=image_url,
    )
    return {"success": result.success, "message_id": result.message_id, "error": result.error}
