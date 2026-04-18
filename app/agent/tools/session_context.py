"""
会话上下文工具函数

提供会话上下文（SessionContext）和会话文件（SessionFile）的存取接口。
"""

import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def get_session_context(session_id: str, context_key: str) -> Optional[Any]:
    """
    获取会话上下文的值

    Args:
        session_id: 会话ID
        context_key: 上下文键

    Returns:
        上下文值，不存在则返回 None
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionContext
        stmt = select(SessionContext.context_value).where(
            SessionContext.session_id == session_id,
            SessionContext.context_key == context_key,
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return row


async def set_session_context(
    session_id: str,
    context_key: str,
    context_value: Any,
) -> None:
    """
    设置会话上下文（存在则更新，不存在则创建）

    Args:
        session_id: 会话ID
        context_key: 上下文键
        context_value: 上下文值
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionContext
        from sqlalchemy import select

        stmt = select(SessionContext).where(
            SessionContext.session_id == session_id,
            SessionContext.context_key == context_key,
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.context_value = context_value
        else:
            record = SessionContext(
                session_id=session_id,
                context_key=context_key,
                context_value=context_value,
            )
            db.add(record)

        await db.commit()


async def get_all_session_contexts(session_id: str) -> Dict[str, Any]:
    """
    获取会话的所有上下文

    Args:
        session_id: 会话ID

    Returns:
        包含所有上下文的字典 {key: value}
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionContext
        stmt = select(SessionContext.context_key, SessionContext.context_value).where(
            SessionContext.session_id == session_id,
        )
        result = await db.execute(stmt)
        rows = result.all()
        return {row[0]: row[1] for row in rows}


async def delete_session_context(session_id: str, context_key: str) -> None:
    """
    删除会话上下文

    Args:
        session_id: 会话ID
        context_key: 上下文键
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionContext
        await db.execute(
            delete(SessionContext).where(
                SessionContext.session_id == session_id,
                SessionContext.context_key == context_key,
            )
        )
        await db.commit()


# ============ 会话文件操作 ============

async def add_session_file(
    session_id: str,
    file_path: str,
    file_type: str = "other",
    absolute_path: Optional[str] = None,
    size: int = 0,
    language: Optional[str] = None,
    is_entrypoint: bool = False,
) -> None:
    """
    添加会话生成的文件记录

    Args:
        session_id: 会话ID
        file_path: 相对路径
        file_type: 文件类型 (project/entrypoint/dependency/config/static/other)
        absolute_path: 绝对路径
        size: 文件大小
        language: 编程语言
        is_entrypoint: 是否主入口文件
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionFile
        record = SessionFile(
            session_id=session_id,
            file_path=file_path,
            absolute_path=absolute_path,
            file_type=file_type,
            size=size,
            language=language,
            is_entrypoint=is_entrypoint,
        )
        db.add(record)
        await db.commit()


async def add_session_files(
    session_id: str,
    files: List[Dict[str, Any]],
) -> None:
    """
    批量添加会话生成的文件记录

    Args:
        session_id: 会话ID
        files: 文件列表，每个文件包含 file_path, file_type, size 等字段
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionFile
        records = []
        for f in files:
            records.append(SessionFile(
                session_id=session_id,
                file_path=f.get("file_path", ""),
                absolute_path=f.get("absolute_path"),
                file_type=f.get("file_type", "other"),
                size=f.get("size", 0),
                language=f.get("language"),
                is_entrypoint=f.get("is_entrypoint", False),
            ))
        db.add_all(records)
        await db.commit()
        logger.info(f"[SessionContext] 保存文件记录: session={session_id}, count={len(files)}")


async def get_session_files(
    session_id: str,
    file_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    获取会话生成的文件列表

    Args:
        session_id: 会话ID
        file_type: 可选，按文件类型过滤

    Returns:
        文件列表
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionFile
        from sqlalchemy import select

        stmt = select(SessionFile).where(SessionFile.session_id == session_id)
        if file_type:
            stmt = stmt.where(SessionFile.file_type == file_type)
        stmt = stmt.order_by(SessionFile.created_at)

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "id": r.id,
                "file_path": r.file_path,
                "absolute_path": r.absolute_path,
                "file_type": r.file_type,
                "size": r.size,
                "language": r.language,
                "is_entrypoint": r.is_entrypoint,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]


async def delete_session_files(session_id: str) -> None:
    """
    删除会话的所有文件记录

    Args:
        session_id: 会话ID
    """
    async with AsyncSessionLocal() as db:
        from app.models import SessionFile
        await db.execute(delete(SessionFile).where(SessionFile.session_id == session_id))
        await db.commit()
