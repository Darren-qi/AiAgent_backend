"""Agent Schema"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class AgentExecuteRequest(BaseModel):
    """Agent 执行请求"""
    task: str = Field(..., description="要执行的任务")
    session_id: Optional[str] = Field(None, description="会话 ID")
    strategy: Optional[str] = Field(None, description="LLM 路由策略")
    context: Optional[Dict[str, Any]] = Field(None, description="额外上下文")


class AgentExecuteResponse(BaseModel):
    """Agent 执行响应"""
    success: bool
    task_id: str
    result: Optional[Dict[str, Any]] = None
    intent: Optional[str] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None


class BudgetStatusResponse(BaseModel):
    """预算状态响应"""
    daily_limit: float
    daily_used: float
    daily_remaining: float
    monthly_limit: float
    monthly_used: float
    monthly_remaining: float
    status: str
    warning_threshold: float
    degradation_threshold: float


class ModelInfo(BaseModel):
    """模型信息"""
    name: str
    provider: str
    display_name: str
    max_tokens: int
    context_window: int
    input_cost: float
    output_cost: float
    enabled: bool
