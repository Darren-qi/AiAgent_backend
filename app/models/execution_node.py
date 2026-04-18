"""
执行节点模型

存储 Agent 执行过程中的每个节点信息。
用于追踪 Thought-Planning-NextMoves-Observation 循环中的每个步骤。

数据库表:
    - execution_nodes: 执行节点表
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, IDMixin, TimestampMixin


class ExecutionNode(Base, IDMixin, TimestampMixin):
    """
    执行节点模型表 (execution_nodes)

    记录 Thought-Planning-NextMoves-Observation (TPNO) 循环中的每个节点。
    完整记录 Agent 的执行过程，便于调试和复现。

    节点类型 (node_type):
        - thought: 思考阶段，分析当前状态
        - planning: 规划阶段，制定执行计划
        - next_moves: 执行阶段，执行具体动作
        - observation: 观察阶段，验证执行结果

    主要字段:
        - session_id: 所属会话ID
        - task_id: 所属任务ID (可选)
        - iteration: 迭代序号
        - todo_id: 待办序号 (所属待办项)
        - node_type: 节点类型
        - content: 节点内容 (思考/规划内容)
        - action: 执行动作 (仅 next_moves)
        - params: 执行参数 (JSON, 仅 next_moves)
        - result: 执行结果 (JSON)
        - is_final: 是否为最终状态
        - success: 是否成功

    使用场景:
        - 执行过程可视化
        - 调试执行问题
        - 分析执行效率
        - 复现执行过程

    TPNO 循环说明:
        1. Thought: 分析当前状态，思考如何执行
        2. Planning: 制定具体执行计划
        3. NextMoves: 执行计划中的动作
        4. Observation: 观察执行结果，判断是否完成
    """

    __tablename__ = "execution_nodes"

    # 会话 ID
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID",
    )

    # 任务 ID（可空，流式执行时 TaskModel 可能尚未创建）
    task_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        ForeignKey("tasks.task_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="任务ID",
    )

    # 迭代序号
    iteration: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="迭代序号",
    )

    # 待办序号 (所属待办项)
    todo_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="待办序号",
    )

    # 节点类型: thought / planning / next_moves / observation
    node_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="节点类型",
    )

    # 节点内容
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="节点内容",
    )

    # 执行动作 (仅 next_moves 类型)
    action: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="执行动作",
    )

    # 执行参数 (JSON, 仅 next_moves 类型)
    params: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="执行参数",
    )

    # 执行结果 (JSON)
    result: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="执行结果",
    )

    # 是否为最终状态
    is_final: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否为最终状态",
    )

    # 是否成功
    success: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否成功",
    )

    # 额外数据 (JSON)
    meta_data: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="元数据",
    )
