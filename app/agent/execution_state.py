"""
执行状态管理器 - 管理任务执行中的完整上下文状态

功能：
1. 管理待办列表（按顺序执行）
2. 维护执行历史 (scratchpad)
3. 记录错误
4. 持久化状态到数据库（断点恢复）
5. 与 TaskManager 联动实现中断

设计原则：
- 状态变更后立即持久化，确保中断可恢复
- scratchpad 超长时自动截断，避免存储爆炸
- 与 session 绑定，支持多会话并发
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class TodoStatus:
    """待办项状态常量"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TodoItem:
    """待办项"""
    id: str
    title: str
    description: str = ""
    status: str = TodoStatus.PENDING
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    error: str = ""
    created_at: int = 0
    completed_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "action": self.action,
            "params": self.params,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TodoItem":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            status=d.get("status", TodoStatus.PENDING),
            action=d.get("action", ""),
            params=d.get("params", {}),
            result=d.get("result", ""),
            error=d.get("error", ""),
            created_at=d.get("created_at", 0),
            completed_at=d.get("completed_at"),
        )


@dataclass
class ActionResult:
    """Action 执行结果"""
    action_name: str
    action_input: dict[str, Any]
    observation: str
    success: bool
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionStateManager:
    """
    统一执行状态管理器

    职责：
    1. 管理待办列表（按顺序执行）
    2. 维护执行历史 (scratchpad)
    3. 记录错误
    4. 持久化到数据库（断点恢复）
    5. 响应中断检查
    """

    # 工作记忆 key
    _STATE_KEY = "execution_state"

    def __init__(
        self,
        session_id: str,
        task_id: str,
        user_input: str = "",
        max_iterations: int | None = None,
        max_scratchpad_length: int = 3000,
    ):
        self.session_id = session_id
        self.task_id = task_id
        self.user_input = user_input
        self.max_iterations = int(os.getenv("AGENT_MAX_ROUNDS", "30")) if max_iterations is None else max_iterations
        self._round_window = self.max_iterations
        self.max_scratchpad_length = max_scratchpad_length

        # 核心状态
        self.todos: list[TodoItem] = []
        self.current_todo_index: int = 0
        self.iteration: int = 0
        self.scratchpad: str = ""
        self.errors: list[dict[str, Any]] = []
        # 失败收尾断点标记（2026-11-14 用户定：失败也支持断点继续）：
        # 非空=上一轮以失败收尾，随状态落库，下一轮由 cap_restore 判续/弃
        self.failed_error: str = ""
        # 阶段八 P1：执行中的动作标记（写前快照）。非空=上一次落库时
        # 某个 action 正在执行 → 崩溃/超时后恢复能知道"卡在哪一步"。
        self.pending_action: dict[str, Any] | None = None
        self.last_action_result: ActionResult | None = None
        self._is_running: Callable[[], bool] | None = None
        self._pg_saver = None

        # 阶段八 P1：断点可靠性
        # - version 乐观锁基线：load_state 读回，save_state 写 version+1，
        #   CAS 失败=同会话并发覆盖（不再静默丢断点）
        # - save_failures/last_save_error：写失败不再只 log
        # - on_checkpoint_error(reason, info)：上报回调（AgentGraph 接 SSE）
        self._version: int = 0
        self.save_failures: int = 0
        self.last_save_error: str = ""
        self.on_checkpoint_error: Callable[[str, dict[str, Any]], None] | None = None

        self._init_scratchpad()

    def _report_checkpoint_error(self, reason: str, detail: str = ""):
        """断点写失败上报（阶段八 P1）：不再只写日志。

        reason: save_failed | version_conflict
        """
        cb = self.on_checkpoint_error
        if not cb:
            return
        try:
            cb(reason, {"detail": str(detail)[:500], "session_id": self.session_id})
        except Exception:
            logger.warning("[ExecutionStateManager] 断点上报回调异常", exc_info=True)

    def _init_scratchpad(self):
        self.scratchpad = ""
        self._append_scratchpad("【任务开始】\n")
        self._append_scratchpad(f"用户输入: {self.user_input[:200]}\n")

    # ============== 中断检查 ==============

    def set_running_check(self, checker: Callable[[], bool]):
        """设置运行状态检查器"""
        self._is_running = checker

    def is_running(self) -> bool:
        """检查任务是否还在运行"""
        if self._is_running:
            return self._is_running()
        return True

    # ============== 待办列表管理 ==============

    def set_todos(self, todos: list[dict[str, Any]]):
        """设置待办列表（从 planner 获取）"""
        self.todos = []
        for i, todo in enumerate(todos):
            self.todos.append(TodoItem(
                id=str(todo.get("id", f"todo_{i}")),
                title=todo.get("title") or todo.get("description", "未命名"),
                description=todo.get("description", ""),
                action=todo.get("action", ""),
                params=todo.get("params", {}),
                created_at=int(time.time()),
            ))
        self.current_todo_index = 0
        self._append_scratchpad(f"【待办列表】共 {len(self.todos)} 项\n")
        for i, todo in enumerate(self.todos):
            self._append_scratchpad(f"  {i+1}. {todo.title} [{todo.action}]\n")

    def get_current_todo(self) -> TodoItem | None:
        """获取当前待办项"""
        idx = self.current_todo_index
        if 0 <= idx < len(self.todos):
            todo = self.todos[idx]
            if todo.status == TodoStatus.PENDING:
                return todo
        return None

    def get_next_pending_todo(self) -> TodoItem | None:
        """获取下一个待处理的待办项"""
        for i, todo in enumerate(self.todos):
            if todo.status == TodoStatus.PENDING:
                self.current_todo_index = i
                return todo
        return None

    def is_all_todos_completed(self) -> bool:
        """全部待办都真正 COMPLETED 才算 True。

        FAILED 不能混进"已完成"：否则最后一个待办一失败，内层循环顶端
        立刻判定"所有待办项已完成"终止，当前待办永远得不到重试
        （2026-11-09 生产实测 task21：测试失败 0 次重试直接收尾）。
        """
        for todo in self.todos:
            if todo.status != TodoStatus.COMPLETED:
                return False
        return True

    def has_unrecoverable_error(self) -> bool:
        error_count = sum(1 for t in self.todos if t.status == TodoStatus.FAILED)
        return error_count >= 3

    def mark_todo_complete(self, todo_id: str, result: str = ""):
        for todo in self.todos:
            if todo.id == todo_id:
                todo.status = TodoStatus.COMPLETED
                todo.result = result
                todo.completed_at = int(time.time())
                self._append_scratchpad(
                    f"【待办完成】{todo.title}\n  结果: {result[:100]}...\n"
                )
                break

    def mark_todo_failed(self, todo_id: str, error: str):
        for todo in self.todos:
            if todo.id == todo_id:
                todo.status = TodoStatus.FAILED
                todo.error = error
                self._append_scratchpad(
                    f"【待办失败】{todo.title}\n  错误: {error[:100]}...\n"
                )
                self.errors.append({"todo_id": todo_id, "error": error})
                break

    def update_todo_params(self, todo_id: str, params: dict[str, Any]):
        """更新待办项的参数"""
        for todo in self.todos:
            if todo.id == todo_id:
                todo.params = params
                break

    def insert_todo_front(self, todo: TodoItem):
        """将待办插入到队列前端（用于重试）"""
        self.todos.insert(0, todo)

    # ============== Scratchpad 管理 ==============

    def _append_scratchpad(self, content: str):
        self.scratchpad += content
        if len(self.scratchpad) > self.max_scratchpad_length:
            if "Observation:" in self.scratchpad:
                obs_part = self.scratchpad.split("Observation:")[-1]
                self.scratchpad = "...[已截断]...\n" + obs_part
            else:
                self.scratchpad = self.scratchpad[-self.max_scratchpad_length:]

    def append_thought(self, thought: str):
        self._append_scratchpad(f"\n【思考】{thought[:300]}\n")

    def append_action(self, action_name: str, action_input: dict[str, Any]):
        input_str = json.dumps(action_input, ensure_ascii=False)[:300]
        self._append_scratchpad(f"\n行动: {action_name}\n输入: {input_str}\n")

    def append_observation(self, observation: str):
        obs = observation[:500] if len(observation) > 500 else observation
        self._append_scratchpad(f"观察: {obs}\n")

    # ============== 执行控制 ==============

    def check_termination(self) -> tuple[bool, str]:
        """检查循环终止条件"""
        if self.iteration >= self.max_iterations:
            return True, "达到最大迭代次数"
        if self.is_all_todos_completed():
            return True, "所有待办项已完成"
        if self.has_unrecoverable_error():
            return True, "存在不可恢复的错误"
        if not self.is_running():
            return True, "用户中断"
        return False, ""

    def next_iteration(self):
        self.iteration += 1

    def extend_budget(self):
        """被轮次上限截断后用户继续 -> 追加一个窗口的轮次预算"""
        self.max_iterations = self.iteration + self._round_window

    def advance_todo(self):
        """推进到下一个待办"""
        self.current_todo_index += 1

    # ============== 状态持久化（使用 WorkingMemory） ==============

    async def _get_pg_saver(self):
        """延迟获取数据库连接"""
        if self._pg_saver is None:
            try:
                from app.agent.memory.pgsaver import PostgresSaver
                from app.db.session import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    self._pg_saver = PostgresSaver(session)
                logger.info(f"[ExecutionStateManager] 数据库连接已获取: session={self.session_id}")
            except Exception as e:
                logger.error(f"[ExecutionStateManager] 无法获取 DB 连接: {e}")
                return None
        return self._pg_saver

    async def save_state(self) -> bool:
        """
        将完整状态保存到数据库（WorkingMemory 表）

        保存内容：
        - todos: 所有待办项状态
        - scratchpad: 执行历史
        - current_todo_index: 当前执行位置
        - iteration: 当前迭代次数
        - user_input: 用户原始输入
        - errors: 错误记录
        """
        if not self.session_id:
            return False

        saver = await self._get_pg_saver()
        if not saver:
            return False

        try:
            next_version = self._version + 1
            state_data = {
                "scratchpad": self.scratchpad,
                "user_input": self.user_input,
                "todos": [t.to_dict() for t in self.todos],
                "current_todo_index": self.current_todo_index,
                "iteration": self.iteration,
                "errors": self.errors,
                "failed_error": self.failed_error,
                "pending_action": self.pending_action,
                "version": next_version,
                "saved_at": time.time(),
            }
            saved_id = await saver.save_working(
                session_id=self.session_id,
                memory_key=self._STATE_KEY,
                memory_value=state_data,
                expected_version=self._version,
            )
            if not saved_id:
                # 乐观锁冲突：有人在本轮之外写了同一行（同会话并发）
                # → 采纳库里较新的 base 重试一次；仍失败才算写失败并上报
                conflict_detail = f"expected={self._version}"
                stored = await saver.get_working(self.session_id, self._STATE_KEY)
                stored_val = (stored or {}).get("value") or {}
                if isinstance(stored_val, dict):
                    self._version = int(stored_val.get("version", 0) or 0)
                    state_data["version"] = self._version + 1
                    saved_id = await saver.save_working(
                        session_id=self.session_id,
                        memory_key=self._STATE_KEY,
                        memory_value=state_data,
                        expected_version=self._version,
                    )
                if not saved_id:
                    self.save_failures += 1
                    self.last_save_error = f"version_conflict({conflict_detail})"
                    logger.error(
                        "[checkpoint_error] 断点写入被并发覆盖且重试失败: "
                        f"session={self.session_id}, {conflict_detail}"
                    )
                    self._report_checkpoint_error("version_conflict", conflict_detail)
                    return False
                logger.warning(
                    f"[ExecutionStateManager] 断点并发覆盖，已采纳新基线并重试成功: "
                    f"session={self.session_id}, {conflict_detail}"
                )
            self._version = int(state_data["version"])
            logger.info(
                f"[ExecutionStateManager] 保存状态成功: "
                f"session={self.session_id}, todos={len(self.todos)}, "
                f"iteration={self.iteration}, version={self._version}"
            )
            return True
        except Exception as e:
            self.save_failures += 1
            self.last_save_error = str(e)
            logger.error(f"[checkpoint_error] 保存状态失败: {e}")
            self._report_checkpoint_error("save_failed", str(e))
            return False

    async def load_state(self) -> bool:
        """
        从数据库加载状态

        Returns:
            True: 加载成功并恢复了状态
            False: 无保存状态或加载失败
        """
        if not self.session_id:
            return False

        saver = await self._get_pg_saver()
        if not saver:
            return False

        try:
            result = await saver.get_working(self.session_id, self._STATE_KEY)
            if not result or not result.get("value"):
                return False

            state_data = result["value"]

            # 恢复 todos
            todos_raw = state_data.get("todos", [])
            self.todos = [TodoItem.from_dict(t) for t in todos_raw]

            # 恢复 scratchpad
            self.scratchpad = state_data.get("scratchpad", "")

            # 恢复执行位置
            self.current_todo_index = state_data.get("current_todo_index", 0)

            # 恢复迭代次数
            self.iteration = state_data.get("iteration", 0)

            # 恢复错误记录
            self.errors = state_data.get("errors", [])
            # 恢复失败收尾标记（旧状态行无此键=空，向后兼容）
            self.failed_error = state_data.get("failed_error", "") or ""
            # 恢复"正在执行的动作"标记（旧状态行无此键=None）
            pa = state_data.get("pending_action")
            self.pending_action = pa if isinstance(pa, dict) else None
            # 恢复乐观锁基线（旧状态行无 version 键=0）
            self._version = int(state_data.get("version", 0) or 0)

            logger.info(
                f"[ExecutionStateManager] 状态已恢复: "
                f"session={self.session_id}, todos={len(self.todos)}, "
                f"iteration={self.iteration}"
            )
            return True
        except Exception as e:
            logger.warning(f"[ExecutionStateManager] 加载状态失败: {e}")
            return False

    async def clear_state(self) -> bool:
        """清除保存的状态"""
        if not self.session_id:
            return False

        saver = await self._get_pg_saver()
        if not saver:
            return False

        try:
            await saver.delete_working(self.session_id, self._STATE_KEY)
            logger.debug(f"[ExecutionStateManager] 状态已清除: session={self.session_id}")
            return True
        except Exception as e:
            logger.warning(f"[ExecutionStateManager] 清除状态失败: {e}")
            return False

    def note_failure(self, error: str):
        """失败收尾记断点（不抹未完成事项，供下一轮断点继续）。

        保留 todos/进度，把失败原因写入 failed_error 与 scratchpad；
        下一轮 load_state 后由 roundcap_judge.cap_restore 的 judge_continue
        决定续跑（恢复未完成待办）还是弃用（用户开了新任务）。
        """
        self.failed_error = str(error or "")
        self._append_scratchpad(f"【任务失败收尾】{self.failed_error[:300]}\n")

    def prepare_resume(self):
        """断点续跑前复位：FAILED/IN_PROGRESS 待办回 pending（恢复即重试），
        并消费掉失败标记（已判定为继续）。"""
        for t in self.todos:
            if t.status in (TodoStatus.FAILED, TodoStatus.IN_PROGRESS):
                t.status = TodoStatus.PENDING
                t.error = ""
        self.failed_error = ""
        # 阶段八 P1：上次落库时有动作正在执行 → 写前快照就是"卡在哪一步"的
        # 证据（journal 的 running 行同理，这里即使 op还没登记也有）。用完即清。
        if self.pending_action:
            pa = self.pending_action or {}
            self._append_scratchpad(
                f"【断点】上次中断时正在执行: {pa.get('action') or '?'} "
                f"(params#{pa.get('params_digest') or '-'})\n"
            )
            self.pending_action = None

    def begin_pending_action(self, action: str, params: dict[str, Any]):
        """执行 action 前记入快照（阶段八 P1，配合 save_state 做写前落库）。

        只存动作名 + 参数摘要（sha256 前 8 位）：快照会进前端/日志，
        参数原文可能含路径、命令等噪音甚至敏感内容。
        """
        try:
            digest = hashlib.sha256(
                json.dumps(params or {}, sort_keys=True, ensure_ascii=False,
                           default=str).encode("utf-8")
            ).hexdigest()[:8]
        except Exception:
            digest = "-"
        self.pending_action = {
            "action": str(action or ""),
            "params_digest": digest,
            "started_at": time.time(),
        }

    def end_pending_action(self):
        """动作收尾（无论成败）：把"正在执行"标记清掉。"""
        self.pending_action = None

    def get_recovery_info(self) -> dict[str, Any]:
        """获取恢复信息摘要（用于前端显示）"""
        return {
            "todos": [t.to_dict() for t in self.todos],
            "current_todo_index": self.current_todo_index,
            "iteration": self.iteration,
            "user_input": self.user_input,
        }
