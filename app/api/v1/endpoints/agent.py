# -*- coding: utf-8 -*-
"""Agent 端点"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncio
import json

from loguru import logger

from app.api.deps import CurrentUser, OptionalCurrentUser
from app.db.session import get_db, AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.schemas.agent import AgentExecuteRequest, AgentExecuteResponse
from app.agent.graphs.main_graph import AgentGraph
from app.agent.memory.manager import MemoryManager
from app.agent.llm.factory import LLMFactory
from app.agent.tools.storage.manager import StorageManager
from app.agent.task_executor import task_manager
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard
from app.models.experience import SessionModel

router = APIRouter()


async def _load_hist_note(db: AsyncSession, session_id: str, cur_task: str,
                          limit: int = 6) -> str:
    """多轮历史块（模块级）：非流式 execute 用；语义同流式 _history_note。"""
    try:
        from app.agent.memory.pgsaver import PostgresSaver
        msgs = await PostgresSaver(db).get_messages(session_id, limit=200)
    except Exception:  # noqa: BLE001 - 历史缺失不影响执行
        msgs = []
    finally:
        # 只读查询会留下 idle-in-transaction 占住连接；显式归还，防连接池耗尽
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    msgs = msgs[-(limit + 1):]
    if msgs and (msgs[-1].get("content") or "").strip() == (cur_task or "").strip():
        msgs = msgs[:-1]  # 去掉刚写入的本轮任务
    lines = [f"{'用户' if m.get('role') == 'user' else '助手'}: {(m.get('content') or '').strip()[:300]}"
             for m in msgs[-limit:]
             if (m.get("content") or "").strip() and m.get("role") in ("user", "assistant")]
    return ("【历史对话】（仅供理解上下文，不要重复执行历史内容）\n"
            + "\n".join(lines)) if lines else ""

input_guard = InputGuard()
output_guard = OutputGuard()
# memory_managers 存储 (MemoryManager, AsyncSession) 元组，AsyncSession 需在请求结束时提交
memory_managers: Dict[str, tuple] = {}
# 会话与任务路径的映射: {session_id: task_folder_name}
session_task_paths: Dict[str, str] = {}
# 追踪运行中的任务: {session_id: (asyncio.Task, AgentGraph)}
running_tasks: Dict[str, tuple] = {}


async def _finalize_db_task(task_id: str, status: str, error: str = "") -> None:
    """把 tasks 表状态写成最终值。

    原先任务记录创建时写 status='running' 后再没人更新过，导致所有任务
    永远停在 running（失败的也是 running），看起来就是"任务没执行完"。
    """
    try:
        from sqlalchemy import update
        from app.models.experience import TaskModel
        async with AsyncSessionLocal() as s:
            stmt = (
                update(TaskModel)
                .where(TaskModel.task_id == task_id)
                .values(status=status, error=error or "", updated_at=datetime.now(timezone.utc))
            )
            if status != "completed":
                # 已完成的任务不被"客户端断连"覆盖成 failed
                stmt = stmt.where(TaskModel.status != "completed")
            await s.execute(stmt)
            await s.commit()
    except Exception as e:
        logger.warning(f"[Agent] 更新任务最终状态失败: {e}")


async def _persist_assistant(session_id: str, content: str,
                              metadata: Optional[Dict[str, Any]] = None) -> None:
    """落库 assistant 最终回答（独立协程 + 独立 DB 会话）。

    不能依赖请求作用域的 db / memory_managers：图内部 on_step("complete")
    后客户端一断开，_real_execute_task 会被 CancelledError 打断，请求作用域
    的落库点根本执行不到（旧代码因此 assistant 从未落库）。
    """
    try:
        from app.agent.memory.pgsaver import PostgresSaver
        async with AsyncSessionLocal() as save_db:
            await PostgresSaver(save_db).save_message(
                session_id=session_id,
                role="assistant",
                content=content,
                metadata=metadata,
            )
            await save_db.commit()
        logger.info(f"[Agent] assistant 消息已落库: session={session_id}, len={len(content)}")
    except asyncio.CancelledError:
        logger.warning(f"[Agent] assistant 落库协程被取消: session={session_id}")
        raise
    except Exception as e:  # noqa: BLE001 - 落库失败不改变任务结果
        logger.error(f"[Agent] assistant 消息落库失败: {session_id}, {e}")


# 会话内存存储（消息数据）
sessions_store: Dict[str, dict] = {}

def _update_session_task_path(session_id: str, task_path: str):
    """更新会话的任务路径（内存 + 数据库）"""
    if session_id in sessions_store:
        sessions_store[session_id]["task_path"] = task_path
        sessions_store[session_id]["updated_at"] = datetime.now().isoformat() + "Z"
    session_task_paths[session_id] = task_path


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: str = "新会话"
    user_input: str = ""
    files: Optional[List[dict]] = None


@router.post("/execute/", response_model=AgentExecuteResponse)
async def execute_task(
    request: AgentExecuteRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
) -> AgentExecuteResponse:
    """执行 Agent 任务"""
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        return AgentExecuteResponse(
            success=False,
            error=error_msg,
            task_id="",
            result={}
        )

    # 注意：括号确保 request.session_id 优先被使用
    session_id = request.session_id or f"{user['id']}_{request.task[:20]}"
    db = AsyncSessionLocal()

    if session_id not in memory_managers:
        memory_managers[session_id] = (MemoryManager(session_id, db), db)

    _memory_manager, _ = memory_managers[session_id]
    await _memory_manager.add_user_message(request.task)

    # 确保会话在数据库中存在（否则 execution_nodes 外键会失败）。
    # 落库失败必须显式报错——旧版静默降级内存存储，"看似成功、刷新全丢"
    session_created = False
    try:
        async with AsyncSessionLocal() as db2:
            from sqlalchemy import select
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db2.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                now = datetime.now(timezone.utc)
                db_session = SessionModel(
                    session_id=session_id,
                    user_id=user["id"],
                    title=request.task[:50] if request.task else "新会话",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                db2.add(db_session)
                await db2.commit()
                session_created = True
                logger.info(f"[Agent] 创建数据库会话: {session_id}")
            else:
                logger.debug(f"[Agent] 会话已存在: {session_id}")
    except Exception as e:
        logger.error(f"[Agent] 创建会话记录失败（显式报错，不再静默降级）: {e}")
        raise HTTPException(status_code=503, detail="会话创建失败，请稍后重试")

    graph = AgentGraph()
    result = await graph.execute(
        task=request.task,
        context={"user_id": user["id"] if user else None, "session_id": session_id,
                 "history_note": await _load_hist_note(db, session_id, request.task)}
    )

    if result.get("success"):
        await _memory_manager.add_assistant_message(str(result.get("result", "")))
        # 提交数据库会话（保存 conversation_messages）
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"[Agent] 数据库会话提交失败: {e}")

    is_safe_output, warning = output_guard.check(str(result.get("result", "")))
    if not is_safe_output:
        result["result"] = output_guard.mask_sensitive(str(result.get("result", "")))

    return AgentExecuteResponse(
        success=result.get("success", False),
        task_id=session_id,
        result=result,
        intent=result.get("intent"),
        warning=warning,
    )


@router.post("/execute/stream")
async def execute_task_stream(
    request: AgentExecuteRequest,
    user: CurrentUser,
) -> StreamingResponse:
    """执行 Agent 任务（流式返回）"""
    # 安全检查
    is_safe, error_msg = input_guard.check(request.task)
    if not is_safe:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'message': error_msg})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    # 记录请求开始
    import sys
    session_id = request.session_id or f"{user['id']}_{request.task[:20]}"
    sys.stderr.write(f"[Agent] ====== execute/stream: session_id={session_id} ======\n")
    sys.stderr.flush()

    # 创建数据库会话，用于 MemoryManager 和会话记录
    db = AsyncSessionLocal()

    # 确保会话在数据库中存在（否则 execution_nodes 外键会失败）
    session_created = False
    logger.info(f"[Agent] 检查会话是否存在: {session_id}")
    try:
        # 检查会话是否已存在
        from sqlalchemy import select
        from app.models.experience import SessionModel
        stmt = select(SessionModel).where(SessionModel.session_id == session_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if not existing:
            logger.info(f"[Agent] 会话不存在，准备创建: {session_id}")
            task_folder = session_task_paths.get(session_id)
            now = datetime.now(timezone.utc)
            db_session = SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else 0,
                title=request.task[:50] if request.task else "新会话",
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(db_session)
            await db.commit()
            session_created = True
            logger.info(f"[Agent] 创建数据库会话成功: {session_id}")
        else:
            # 兜底创建方（main_graph 里那段）会写死 user_id=0 / title="Agent Session"，
            # 这里按当前登录态校正归属，否则刷新后 list-sessions 按真实 user_id 过滤查不到
            if user:
                want_uid = user["id"]
                want_title = (request.task or "")[:50]
                if (existing.user_id or 0) != want_uid or existing.title == "Agent Session":
                    existing.user_id = want_uid
                    if want_title and existing.title in (None, "", "Agent Session", "新会话"):
                        existing.title = want_title
                    await db.commit()
                    logger.info(f"[Agent] 会话归属已校正: {session_id} -> user_id={want_uid}")
                else:
                    logger.debug(f"[Agent] 会话已存在: {session_id}")
            else:
                logger.debug(f"[Agent] 会话已存在: {session_id}")
    except Exception as e:
        import traceback
        logger.error(f"[Agent] 创建会话记录失败（显式报错，不再静默降级）: {e}")
        logger.error(f"[Agent] 完整错误: {traceback.format_exc()}")
        raise HTTPException(status_code=503, detail="会话创建失败，请稍后重试")

    # 初始化 MemoryManager，传入数据库会话（这样 conversation_messages 会被保存）
    if session_id not in memory_managers:
        memory_managers[session_id] = (MemoryManager(session_id, db), db)
    else:
        # 已存在的 manager 不再覆盖，保持原样
        pass

    _memory_manager, _ = memory_managers[session_id]
    await _memory_manager.add_user_message(request.task)

    # 任务路径
    task_folder = session_task_paths.get(session_id)
    logger.debug(f"[Agent] 当前会话任务路径: {task_folder}")

    # 定义流式生成器
    async def event_stream():
        # 创建一个队列用于收集事件
        queue = asyncio.Queue()

        # 心跳间隔（秒）
        heartbeat_interval = 30

        # 捕获 final_summary：这是最终回答的干净文本（complete 事件里的
        # result 在 LangGraph 下是步骤转储），用于会话结束后落库 assistant 消息。
        # persist_state：一旦取到文本立刻 create_task 落库 —— 图内部的
        # on_step("complete") 会让前端/客户端断开，_real_execute_task 随即被
        # CancelledError 打断，放在返回后的落库点会永远执行不到
        # （2026-11-10 本地 e2e 实测：断连后 assistant 消息丢失、任务被标 failed）。
        # 结构化落库：建议不再拼进正文（拼接后历史回放只能显示成纯文字），
        # 走 metadata.suggestions → get-session 组回 complete 步骤的可点击建议
        persist_state = {"text": "", "scheduled": False}

        def _schedule_persist(text_value: str, metadata: Optional[Dict[str, Any]] = None):
            text_value = (text_value or "").strip()
            if not text_value or persist_state["scheduled"]:
                return
            persist_state["scheduled"] = True
            asyncio.create_task(_persist_assistant(session_id, text_value, metadata))

        # 定义回调函数，将事件添加到队列
        def on_step(step_type: str, data: Dict[str, Any]):
            if step_type == "final_summary":
                try:
                    text = (data.get("summary") or "").strip()
                    suggestions = data.get("suggestions") or []
                    if text:
                        persist_state["text"] = text
                        _schedule_persist(text, {"suggestions": suggestions} if suggestions else None)
                except Exception:  # noqa: BLE001 - 捕获失败不影响推送
                    pass
            elif step_type == "complete":
                # 有些路径（断点恢复后无新执行）不发 final_summary，
                # 但 complete 事件里可能带纯文本 result → 也落库
                try:
                    v = data.get("result")
                    if isinstance(v, str) and v.strip():
                        persist_state["text"] = persist_state.get("text") or v.strip()
                        _schedule_persist(v)
                except Exception:  # noqa: BLE001
                    pass
            asyncio.create_task(queue.put(f"event: {step_type}\ndata: {json.dumps(data)}\n\n"))

        # 推送开始事件
        yield f"event: start\ndata: {json.dumps({'task_id': session_id, 'task_path': task_folder})}\n\n"

        # 执行任务
        exec_state = {"finished": False}

        async def _history_note(db, sid, cur_task, limit: int = 6) -> str:
            """多轮历史块：只进 thought_context，禁拼 state.task（承诺文件种子化）。"""
            try:
                from app.agent.memory.pgsaver import PostgresSaver
                msgs = await PostgresSaver(db).get_messages(sid, limit=200)
            except Exception:  # noqa: BLE001 - 历史缺失不影响执行
                msgs = []
            finally:
                # 只读查询留下 idle-in-transaction 占连接；显式归还防池耗尽
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            msgs = msgs[-(limit + 1):]
            if msgs and (msgs[-1].get("content") or "").strip() == (cur_task or "").strip():
                msgs = msgs[:-1]  # 去掉刚写入的本轮任务
            lines = [f"{'用户' if m.get('role') == 'user' else '助手'}: {(m.get('content') or '').strip()[:300]}"
                     for m in msgs[-limit:]
                     if (m.get("content") or "").strip() and m.get("role") in ("user", "assistant")]
            return ("【历史对话】（仅供理解上下文，不要重复执行历史内容）\n"
                    + "\n".join(lines)) if lines else ""

        async def _real_execute_task():
            from app.agent.cancel_signal import cancel_signal

            logger.info(f"[Agent] 任务开始执行: session_id={session_id}")

            # 注册取消信号
            cancel_signal.register(session_id)

            try:
                graph = AgentGraph()
                task_manager.create_task(session_id)
                try:
                    result = await graph.execute(
                        task=request.task,
                        session_id=session_id,
                        task_id=session_id,
                        context={
                            "user_id": user["id"] if user else None,
                            "session_id": session_id,
                            "task_path": task_folder,
                            "history_note": await _history_note(db, session_id, request.task),
                        },
                        on_step=on_step
                    )
                    # 执行主体已结束：此后即使前端断开也不再取消本任务
                    exec_state["finished"] = True
                    # 先落库再通知前端 —— 前端收到 complete 会立刻断开，
                    # 若先推事件再写库，取消信号会打断状态回写（任务永远停在 running）
                    # AgentGraph.execute 吞掉异常后正常返回 _format_error(success=False)，
                    # 若这里无脑写 completed，失败任务在库里也显示"完成"
                    # （2026-11-09 实测：任务18 报错却 status=completed）。
                    if isinstance(result, dict) and not result.get("success", True):
                        await _finalize_db_task(
                            session_id, "failed",
                            str(result.get("error") or "任务执行失败"),
                        )
                    else:
                        # 兜底落库：final_summary 已在 on_step 里 create_task 即时
                        # 落库；这里只覆盖 final_summary 缺失的场景（共用去重开关）
                        answer = (persist_state.get("text") or "").strip()
                        if not answer and isinstance(result, dict):
                            for key in ("summary", "result"):
                                val = result.get(key)
                                if isinstance(val, str) and val.strip():
                                    answer = val.strip()
                                    break
                        if answer:
                            _schedule_persist(answer)
                        await _finalize_db_task(session_id, "completed")

                    # 执行完成后，更新会话的任务路径
                    if task_folder:
                        _update_session_task_path(session_id, task_folder)

                    # 最后才推送完成事件
                    await queue.put(f"event: complete\ndata: {json.dumps(result)}\n\n")
                finally:
                    # 清理引用
                    task_manager.complete_task(session_id)
                    running_tasks.pop(session_id, None)
                    # 提交数据库会话（保存 conversation_messages 等）
                    try:
                        await db.commit()
                        logger.info(f"[Agent] 数据库会话已提交: session_id={session_id}")
                    except Exception as e:
                        logger.error(f"[Agent] 数据库会话提交失败: {e}")
            except asyncio.CancelledError:
                # 前端断开连接或被 abort 端点取消 — 立即推送 stopped 事件
                logger.warning(f"[Agent] 任务被取消: session_id={session_id}")
                task_manager.stop_task(session_id)
                await _finalize_db_task(session_id, "failed", "任务被取消")
                cancel_signal.cancel(session_id)  # 确保取消信号被设置
                await queue.put(f"event: stopped\ndata: {json.dumps({'message': '任务已被终止'})}\n\n")
                raise
            except Exception as e:
                # 推送错误事件（CancelledError 已在上方被捕获，不会到达此处）
                logger.error(f"[Agent] 任务执行异常: {e}")
                await queue.put(f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n")
                task_manager.fail_task(session_id)
                await _finalize_db_task(session_id, "failed", str(e))
            finally:
                # 注销取消信号
                cancel_signal.unregister(session_id)
                # 标记任务完成
                await queue.put(None)

        # 启动任务执行 - 捕获返回的 task 对象
        task_handle = asyncio.create_task(_real_execute_task())
        # 立即注册到 running_tasks（这样 abort 端点可以立即获取到）
        running_tasks[session_id] = (task_handle, None)

        # 从队列中读取事件并推送，同时发送心跳保持连接
        last_heartbeat = asyncio.get_event_loop().time()

        try:
            while True:
                try:
                    # 使用超时等待事件，避免永久阻塞
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)

                    if event is None:
                        # 任务完成
                        break

                    yield event
                    last_heartbeat = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat >= heartbeat_interval:
                        yield f"event: heartbeat\ndata: {json.dumps({'timestamp': current_time})}\n\n"
                        last_heartbeat = current_time
                    # 心跳时也检查中断状态
                    if not task_manager.is_running(session_id):
                        logger.info(f"[Agent] 流循环检测到中断: {session_id}")
                        yield f"event: stopped\ndata: {json.dumps({'message': '任务已被用户中断'})}\n\n"
                        break
        except asyncio.CancelledError:
            # 前端断开连接，取消正在执行的任务
            logger.info(f"[Agent] 前端断开连接，取消任务: {session_id}")
            # 若这轮已经拿到最终回答（final_summary/complete 已到），断连也照样落库，
            # 否则「用户断连」会把这轮的 AI 回复丢掉，历史里只剩一串用户消息
            if (persist_state.get("text") or "").strip():
                _schedule_persist(persist_state["text"].strip())
            running_info = running_tasks.pop(session_id, None)
            if running_info:
                running_task, graph = running_info
                # 关键：调用 Task.cancel() 会在最近的 await 点抛出 CancelledError
                # 这会立即中断 LLM 调用等长时间阻塞操作
                if running_task and not running_task.done() and not exec_state["finished"]:
                    running_task.cancel()
                if graph and not exec_state["finished"]:
                    graph.cancel()
            task_manager.stop_task(session_id)
            raise
        finally:
            # 清理追踪
            running_tasks.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


@router.get("/status/{task_id}")
async def get_task_status(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """获取任务状态"""
    return {
        "task_id": task_id,
        "status": task_manager.get_status(task_id),
        "session_id": task_id,
    }


@router.get("/debug/tasks")
async def debug_tasks() -> Dict[str, Any]:
    """调试端点：查看所有运行中的任务"""
    return {
        "running_tasks_keys": list(running_tasks.keys()),
        "task_manager_all": task_manager.get_all_tasks(),
    }


@router.get("/ping/{task_id}")
async def ping_task(task_id: str) -> Dict[str, Any]:
    """诊断路由：确认 abort 请求是否到达"""
    logger.warning(f"[PING] 收到 ping 请求: {task_id}")
    return {"task_id": task_id, "running_tasks": list(running_tasks.keys())}


@router.post("/abort/{task_id}")
async def abort_task(task_id: str, user: OptionalCurrentUser = None) -> Dict[str, Any]:
    """中止任务"""
    import logging
    from app.agent.cancel_signal import cancel_signal

    logger.info(f"[ABORT] 收到 abort 请求: {task_id}")

    # 1. 通过 CancelSignal 发送取消信号（让 LLM 调用能立即感知）
    cancel_signal.cancel(task_id)

    # 2. 通过 TaskManager 停止（设置状态，但不中断 await）
    stopped = task_manager.stop_task(task_id)

    # 3. 通过 running_tasks 取消 asyncio Task — 这是真正中断 await 的机制
    running_info = running_tasks.pop(task_id, None)
    if running_info:
        running_task, graph = running_info
        # 关键：调用 Task.cancel() 会在最近的 await 点抛出 CancelledError
        if running_task:
            running_task.cancel()
        if graph:
            graph.cancel()

    return {
        "success": True,
        "task_id": task_id,
        "stopped": stopped,
        "cancelled": running_info is not None,
    }

    logger.warning(f"[ABORT] ====== abort 完成: {task_id}, task_manager={stopped} ======")
    return {"task_id": task_id, "aborted": True, "cancelled": True}


# ============ 前端兼容的会话端点 ============
# 注：旧 `_get_db`（async for + break，连接滞留到 GC）已废弃，统一用
# `async with AsyncSessionLocal() as db` 确定性关闭。


@router.get("/list-sessions/")
async def list_sessions(
    user: OptionalCurrentUser = None,
) -> dict:
    """获取会话列表 - 前端兼容（会话绑定用户：未登录返回空，非管理员只看自己的）"""
    # 未登录：不返回任何会话
    if user is None:
        return {
            "code": 200,
            "message": "success",
            "data": {"sessions": [], "total": 0},
        }
    try:
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            stmt = select(SessionModel).order_by(SessionModel.updated_at.desc())
            # 非管理员只看自己的会话（管理员看全部）
            if user.get("role") != "admin":
                stmt = stmt.where(SessionModel.user_id == user["id"])
            stmt = stmt.limit(50)
            result = await db.execute(stmt)
            sessions_db = result.scalars().all()

            sessions = [
                {
                    "session_id": s.session_id,
                    "title": s.title or "未命名会话",
                    "created_at": s.created_at.isoformat() if s.created_at else "",
                    "updated_at": s.updated_at.isoformat() if s.updated_at else "",
                    "task_path": None,  # task_path 存储在 SessionContext 表中
                }
                for s in sessions_db
            ]
            return {
                "code": 200,
                "message": "success",
                "data": {
                    "sessions": sessions,
                    "total": len(sessions)
                }
            }
    except Exception:
        pass

    # 降级到内存存储（内存无归属信息：仅管理员可见，其余返回空，避免跨用户泄露）
    if user.get("role") != "admin":
        return {
            "code": 200,
            "message": "success",
            "data": {"sessions": [], "total": 0},
        }
    sessions = [
        {
            "session_id": sid,
            "title": data.get("title", "未命名会话"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "task_path": data.get("task_path"),
        }
        for sid, data in sessions_store.items()
    ]
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "sessions": sessions,
            "total": len(sessions)
        }
    }


def _build_task_tree(task_path: str) -> list:
    """构建任务目录文件树。

    必须与运行时 project_tree 事件同源：文件由 file_operations skill 写进
    get_tasks_dir()/<task_path>，而 StorageManager 的本地根指向另一处 tasks，
    用它构建恒为空树（2026-11-10 生产实测：目录在磁盘、get-session 返回 []）。
    """
    try:
        if not task_path:
            return []
        from pathlib import Path
        from app.agent.skills.file_operations.skill import get_tasks_dir
        from app.agent.graphs.main_graph import _walk_dir

        base = get_tasks_dir() / task_path
        if not base.exists() or not base.is_dir():
            return []
        children = _walk_dir(Path(base), Path(base))
        # 根节点 = 任务文件夹（对齐运行时 project_tree 事件的树格式）
        return [{
            "name": task_path,
            "path": task_path,
            "type": "folder",
            "children": children,
        }] if children else []
    except Exception as e:  # noqa: BLE001 - 树构建失败不应让会话详情整体 500
        logger.warning(f"[Agent] 构建任务目录树失败: task_path={task_path}, {e}")
        return []


async def _load_db_messages(db, session_id: str) -> tuple[list, list]:
    """从 PG 读会话消息，返回 (前端消息列表, 原始 role 列表)。

    按「轮次」交替组织：user → 该轮 assistant（缺则补该轮执行过程卡）→ 下一轮
    user …，而不是把用户挤在前面、AI 内容全垫在最后（2026-11-10 用户反馈）。
    老会话 assistant 从未落库（修复前 bug），其执行节点按时间戳切到各自轮次；
    各轮 AI 正文已无法找回（tasks.result 空、无 final_summary 节点、无 checkpoint），
    只能用过程卡代表该轮反馈。
    """
    from app.agent.memory.pgsaver import PostgresSaver

    raw = await PostgresSaver(db).get_messages(session_id, limit=500)
    roles = [m.get("role") for m in raw]
    rows = [
        m for m in raw
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]

    # 切轮次：user 开一轮，其后的 assistant 归入该轮
    turns = []
    for m in rows:
        if m.get("role") == "user":
            turns.append({"user": m, "assistant": []})
        elif turns:
            turns[-1]["assistant"].append(m)
        else:
            turns.append({"user": None, "assistant": [m]})

    # 执行节点无条件捞取：过程行（读写/执行）也要随刷新回放，
    # 不能只在「缺正文」时才查（2026-11-12 用户反馈：刷新后过程与样式全丢）
    from sqlalchemy import select
    from app.models.execution_node import ExecutionNode
    nodes = (await db.execute(
        select(ExecutionNode)
        .where(ExecutionNode.session_id == session_id)
        .order_by(ExecutionNode.id)
        .limit(500)
    )).scalars().all()

    step_type_map = {
        "thought": "thinking",
        "planning": "planning",
        # 对齐实时 SSE：用 next_moves（前端才有动作词/关键参数/展开详情模板）
        "next_moves": "next_moves",
        "observation": "observation",
    }

    def _card_for(node_rows):
        steps = []
        for n in node_rows:
            content = (n.content or "").strip()
            if not content:
                continue
            step = {"type": step_type_map.get(n.node_type, "thinking"),
                    "content": content[:2000]}
            if n.node_type == "next_moves" and n.action:
                step["action"] = n.action
            if n.node_type == "next_moves" and n.params:
                step["params"] = n.params
            if n.node_type == "observation":
                if n.success is not None:
                    step["success"] = n.success
                # 非显式失败的成功观察并入上一条动作行（展开详情=读到/写入了什么），
                # 与实时前端合并逻辑一致；失败保留独立行（红字可见）
                if n.success is not False:
                    if steps and steps[-1].get("type") == "next_moves" and "result" not in steps[-1]:
                        steps[-1]["result"] = content[:2000]
                        continue
            steps.append(step)
        return {"type": "thinking", "content": "", "steps": steps} if steps else None

    def _in_window(n, start, end):
        """节点时间落在 [start, end) 才属于该轮；时间比不了就归该轮。"""
        ts = getattr(n, "created_at", None)
        if ts is None or start is None:
            return True
        try:
            if start is not None and ts < start:
                return False
            if end is not None and ts >= end:
                return False
            return True
        except TypeError:
            return True

    messages = []
    for i, t in enumerate(turns):
        nxt_user = turns[i + 1]["user"] if i + 1 < len(turns) else None
        start = (t["user"] or {}).get("created_at")
        end = (nxt_user or {}).get("created_at") if nxt_user else None
        # 下一轮用户时间与本轮相同（重复/批量写入的数据）时窗口为空 → 该轮
        # 永远分不到节点，会出现 user、user 相邻；此时放开上界，宁可节点重复
        if start is not None and end is not None and end <= start:
            end = None
        if t["user"]:
            messages.append({"type": "user", "content": t["user"].get("content") or ""})
        # 过程卡（读写/执行行）在前——与实时顺序一致
        card = _card_for([n for n in nodes if _in_window(n, start, end)])
        if card:
            messages.append(card)
        # 正文卡：type=thinking + complete 步骤 → 走 StepItem 完成渲染
        # （纯文字+样式）。旧方案 type="assistant" 落到前端兜底分支=纯文本
        # 且不渲染 markdown——刷新后样式全丢（2026-11-12 用户反馈）
        if t["assistant"]:
            for a in t["assistant"]:
                content = (a.get("content") or "").strip()
                if not content:
                    continue
                meta = a.get("metadata") or {}
                suggestions = meta.get("suggestions") or []
                # 旧数据救回：历史落库有两代形态——①拼接"📌 建议下一步:"纯文本
                # ②正文含"### 建议下一步"段但未带 metadata。复用 Integrator 的
                # 切段/剥离逻辑解回结构化建议并从正文剥离，恢复可点击（2026-11-12）
                if not suggestions and "建议下一步" in content:
                    from app.agent.graphs.nodes.integrator import Integrator
                    suggestions = Integrator._extract_suggestions(content)
                    content = Integrator._strip_suggestions_section(content)
                step0 = {"type": "complete", "final_answer": content,
                         "collapsed": False}
                if suggestions:
                    step0["suggestions"] = suggestions
                messages.append({
                    "type": "thinking",
                    "content": "",
                    "steps": [step0],
                })

    await db.rollback()  # 只读查询归还连接
    return messages, roles


@router.get("/get-session/")
async def get_session(
    session_id: str = Query(..., description="会话ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """获取会话详情 - 前端兼容

    消息、标题、任务目录一律以数据库为准；sessions_store 仅作兜底，
    且早退分支不得丢弃已算出的 file_tree/task_path
    （2026-11-10 生产 bug：刷新后点历史会话，对话与任务目录全空）。
    """
    file_tree = []
    task_path = None
    title = ""
    db_messages = None

    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db.execute(stmt)
            session_db = result.scalar_one_or_none()

            if session_db:
                title = session_db.title or ""

            # 任务目录/消息一律读库：老会话可能只有 conversation_messages、
            # sessions 表没有行（只在消息表留痕），不能因为 session 行缺失就返回空
            try:
                from app.agent.tools.session_context import get_session_context
                task_path = await get_session_context(session_id, "task_path")
                await db.rollback()
            except Exception:  # noqa: BLE001
                task_path = None
            if not task_path:
                task_path = session_task_paths.get(session_id)
            if task_path:
                file_tree = _build_task_tree(task_path)
            try:
                db_messages, _ = await _load_db_messages(db, session_id)
            except Exception as e:  # noqa: BLE001 - 消息读失败降级到内存兜底
                logger.warning(f"[Agent] 读取会话消息失败: {session_id}, {e}")
                await db.rollback()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Agent] get-session 数据库读取失败: {session_id}, {e}")

    session_data = sessions_store.get(session_id, {})
    if not title:
        title = session_data.get("title", "")
    if not task_path:
        task_path = session_data.get("task_path")
        if task_path and not file_tree:
            file_tree = _build_task_tree(task_path)

    if db_messages is None:
        db_messages = session_data.get("messages", []) or []
    if db_messages:
        messages = db_messages
    else:
        messages = session_data.get("messages", []) or []

    if not session_data and not db_messages and not file_tree:
        # 会话完全不存在：仍返回 code 0（前端严格判 code === 0）
        return {
            "code": 0,
            "message": "success",
            "data": {
                "session_id": session_id,
                "title": title,
                "messages": [],
                "file_tree": [],
                "task_path": task_path
            }
        }

    return {
        "code": 0,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": title,
            "messages": messages,
            "file_tree": file_tree,
            "task_path": task_path,
        }
    }


@router.post("/create-session/")
async def create_session(
    request: CreateSessionRequest,
    user: OptionalCurrentUser = None,
) -> dict:
    """创建新会话 - 前端兼容"""
    import datetime

    session_id = request.session_id or f"session_{datetime.datetime.now().timestamp()}"
    now = datetime.datetime.now().isoformat() + "Z"

    project_name = None
    if request.user_input:
        project_name = _extract_project_name(request.user_input)

    # 注意：不在 create-session 时创建任务目录
    # 任务目录在 execute/stream 首次执行时才创建（带时间戳），后续复用同一目录
    # 这样确保每个会话只有一个任务目录，避免多次创建带不同时间戳的目录
    task_folder = None

    session_data = {
        "session_id": session_id,
        "title": request.title or "新会话",
        "user_input": request.user_input,
        "files": request.files or [],
        "messages": [],
        "file_tree": [],
        "task_path": task_folder,
        "created_at": now,
        "updated_at": now,
    }

    try:
        async with AsyncSessionLocal() as db:
            # 注意：函数内 `import datetime` 把名字绑定成了模块，必须用 datetime.datetime.now()
            # 旧代码 datetime.now(...) = AttributeError 且被 except 吞成假 200（2026-11-10 实锤）
            now = datetime.datetime.now(timezone.utc)
            db_session = SessionModel(
                session_id=session_id,
                user_id=user["id"] if user else 0,
                title=request.title or "新会话",
                status="active",
                created_at=now,
                updated_at=now,
            )
            db.add(db_session)
            await db.commit()
    except Exception as e:
        # 落库失败必须显式报错——静默返 200 会"看似建好、刷新全丢"（2026-11-10 线上根因）
        logger.error(f"[Agent] 保存会话到数据库失败（显式报错，不再静默降级）: {e}")
        raise HTTPException(status_code=503, detail="会话创建失败，请稍后重试")

    sessions_store[session_id] = session_data
    session_task_paths[session_id] = task_folder

    return {
        "code": 200,
        "message": "success",
        "data": {
            "session_id": session_id,
            "title": request.title or "新会话",
            "created_at": now,
            "task_path": task_folder,
        }
    }


def _extract_project_name(task: str) -> Optional[str]:
    """从任务描述中提取项目名称"""
    import re
    # 尝试匹配 "创建一个 XXX 项目" 或 "生成 XXX 应用" 等模式
    patterns = [
        r'(?:创建|生成|开发|构建|制作)\s*`?([a-zA-Z_][a-zA-Z0-9_]*)',
        r'(?:项目|应用|应用|系统|网站|平台|工具)\s*`?([a-zA-Z_][a-zA-Z0-9_]*)',
        r'`([a-zA-Z_][a-zA-Z0-9_]*(?:_project|_app|_project|_system)?)`',
    ]
    for pattern in patterns:
        match = re.search(pattern, task)
        if match:
            name = match.group(1).strip()
            if len(name) >= 2:
                return name
    return None


@router.delete("/execute/")
async def delete_session_by_query(
    task_id: str = Query(..., description="任务ID"),
    user: OptionalCurrentUser = None,
) -> dict:
    """删除会话 - 前端兼容"""
    if task_id in sessions_store:
        del sessions_store[task_id]
    if task_id in session_task_paths:
        del session_task_paths[task_id]

    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete
            stmt = delete(SessionModel).where(SessionModel.session_id == task_id)
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.warning(f"[Agent] 删除会话失败: {e}")

    return {"success": True, "message": "deleted"}


# ---------- 文件读取 / 列表 / 下载（前端预览、重开会话恢复文件树） ----------
# 前端约定：GET /agent/read-file/?file_path=xxx -> {code:0, data:{content}}
# 路径相对 tasks 根目录（如 auto_project_x/a.md），文件树里的 path 已带任务目录前缀。

def _tasks_root():
    from app.agent.skills.file_operations.skill import get_tasks_dir
    return get_tasks_dir().resolve()


def _safe_file(file_path: str):
    """把路径收敛到 tasks 目录内，防目录穿越。"""
    from pathlib import Path
    root = _tasks_root()
    p = Path(file_path)
    p = (p if p.is_absolute() else root / p).resolve()
    if p != root and root not in p.parents:
        raise HTTPException(status_code=400, detail="路径越界")
    return p


@router.get("/read-file/")
async def read_file(file_path: str):
    """读任务目录内文件内容（供右侧预览）。"""
    p = _safe_file(file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if p.is_dir():
        raise HTTPException(status_code=400, detail="是目录，不是文件")
    content = p.read_text(encoding="utf-8", errors="replace")
    return {"code": 0, "message": "ok",
            "data": {"path": file_path, "content": content[:200000],
                     "truncated": len(content) > 200000}}


@router.get("/get-files/")
async def get_files(session_id: str):
    """某会话产出的文件列表（重开会话时恢复文件结构）。"""
    from pathlib import Path
    from sqlalchemy import select
    from app.models import SessionFile
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(SessionFile).where(SessionFile.session_id == session_id)
        )).scalars().all()
    files = [{"name": Path(r.file_path).name, "path": r.file_path, "type": "file"}
             for r in rows if r.file_path]
    return {"code": 0, "message": "ok", "data": {"files": files}}


@router.get("/download-file/")
async def download_file(file_path: str):
    from fastapi.responses import FileResponse
    p = _safe_file(file_path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(p, filename=p.name)


@router.get("/download-dir/")
async def download_dir(dir: str):
    """打包整个任务目录为 zip 下载。"""
    import io
    import zipfile
    from fastapi.responses import StreamingResponse
    p = _safe_file(dir)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="不是目录")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(p.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(p))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition":
                                      f'attachment; filename="{p.name}.zip"'})
