"""Health 端点"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def health_check() -> dict:
    """健康检查"""
    return {
        "status": "healthy",
        "service": "ai-agent",
    }


@router.get("/detailed")
async def detailed_health_check() -> dict:
    """详细健康检查"""
    try:
        from app.agent.llm.factory import LLMFactory
        factory = LLMFactory()
        models = factory.get_available_models()
        budget_info = factory.get_budget_status()
    except Exception:
        models = []
        budget_info = None

    return {
        "status": "healthy",
        "service": "ai-agent",
        "models": {
            "available": len(models) if models else 0,
            "names": [m.name for m in models] if models else [],
        },
        "budget": {
            "status": budget_info.status.value if budget_info else "unknown",
        } if budget_info else {"status": "unknown"},
    }


@router.get("/ready")
async def readiness_check() -> dict:
    """就绪检查"""
    return {"ready": True}


@router.get("/live")
async def liveness_check() -> dict:
    """存活检查"""
    return {"alive": True}
