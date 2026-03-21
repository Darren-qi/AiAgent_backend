# -*- coding: utf-8 -*-
"""Budget 端点"""

from fastapi import APIRouter

from app.api.deps import DBSession, CurrentUser
from app.api.v1.schemas.agent import BudgetStatusResponse
from app.agent.llm.factory import LLMFactory

router = APIRouter()


@router.get("/status", response_model=BudgetStatusResponse)
async def get_budget_status(
    user: CurrentUser = None,
) -> BudgetStatusResponse:
    """获取预算状态"""
    factory = LLMFactory()
    budget_info = factory.get_budget_status()

    return BudgetStatusResponse(
        daily_limit=budget_info.daily_limit,
        daily_used=budget_info.daily_used,
        daily_remaining=budget_info.daily_limit - budget_info.daily_used,
        monthly_limit=budget_info.monthly_limit,
        monthly_used=budget_info.monthly_used,
        monthly_remaining=budget_info.monthly_limit - budget_info.monthly_used,
        status=budget_info.status.value,
        warning_threshold=budget_info.warning_threshold,
        degradation_threshold=budget_info.degradation_threshold,
    )


@router.post("/reset/daily")
async def reset_daily_budget(
    user: CurrentUser = None,
) -> dict:
    """重置每日预算"""
    factory = LLMFactory()
    await factory.budget_manager.reset_daily()
    return {"reset": True, "scope": "daily"}


@router.post("/reset/monthly")
async def reset_monthly_budget(
    user: CurrentUser = None,
) -> dict:
    """重置每月预算"""
    factory = LLMFactory()
    await factory.budget_manager.reset_monthly()
    return {"reset": True, "scope": "monthly"}
