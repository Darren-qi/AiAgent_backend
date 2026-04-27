# -*- coding: utf-8 -*-
"""AutoGen 团队 GroupChat 核心"""

from __future__ import annotations
import asyncio
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent.autogen.team.agents import (
    PM_PROMPT, PM_PROMPT_REQUIREMENTS, PM_PROMPT_ACCEPTANCE,
    ARCHITECT_PROMPT, DEVELOPER_PROMPT, QA_PROMPT, SUPERVISOR_PROMPT,
    AGENT_CONFIG,
)
from app.agent.autogen.team.sub_team import SubTeamDiscussion, parse_sub_team_directive
from app.agent.autogen.tools.skill_bridge import get_tools_for_task, write_artifact
from app.agent.autogen.memory.pg_memory import PGMemory
from app.agent.llm.factory import LLMFactory

logger = logging.getLogger(__name__)

AGENT_NAMES = ["ProductManager", "Architect", "Developer", "QAEngineer", "Supervisor"]

AGENT_PROMPTS: Dict[str, str] = {
    "ProductManager": PM_PROMPT,
    "Architect":      ARCHITECT_PROMPT,
    "Developer":      DEVELOPER_PROMPT,
    "QAEngineer":     QA_PROMPT,
    "Supervisor":     SUPERVISOR_PROMPT,
}

STAGE_NEXT: Dict[str, str] = {
    "init":         "ProductManager",
    "requirements": "Architect",
    "architecture": "Developer",
    "development":  "QAEngineer",
    "qa_pass":      "Architect",
    "architect_review": "ProductManager",
    "qa_fail":      "Developer",
    "acceptance":   "__done__",
    # 新增：development阶段结束后直接进入QA
    "development_done": "QAEngineer",
}

MAX_ITERATIONS = 20
MAX_QA_RETRIES = 3
# 历史超过此轮数时触发摘要压缩（注入 LLM 上下文）
COMPRESS_THRESHOLD = 10


class AgentTeam:
    def __init__(
        self,
        session_id: str,
        task_type: str = "code",
        workspace: str = ".agent_workspace",
        on_message: Optional[Callable[[str, Dict], None]] = None,
        db_session=None,
    ):
        self.session_id = session_id
        self.task_type = task_type
        self.workspace = workspace
        self._on_message = on_message
        self._db_session = db_session
        self._llm = LLMFactory.get_instance()
        self._tools = get_tools_for_task(task_type)
        self._history: List[Dict[str, str]] = []
        self._stage = "init"
        self._qa_retries = 0
        self._task_path: Optional[str] = None
        self._cancelled = False
        self._done = False          # 防止结束后继续推送事件
        self._history_summary: str = ""  # 压缩后的历史摘要
        self._created_files: List[str] = []  # 追踪已创建的文件列表
        self._dev_passes: int = 0  # Developer 自检轮次计数
        # PG Memory 初始化
        self._memory: Optional[PGMemory] = None
        if db_session:
            self._memory = PGMemory(session_id, db_session)

    # ── 内部工具 ──────────────────────────────────────────

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self._done and event_type not in ("done", "stopped", "error"):
            return
        data.setdefault("channel", "main")
        if self._on_message:
            self._on_message(event_type, data)

    def cancel(self) -> None:
        self._cancelled = True

    async def abort(self) -> None:
        self._cancelled = True

    # ── 历史压缩 ──────────────────────────────────────────

    async def _compress_history(self) -> None:
        """超过阈值时将旧历史压缩为摘要，保留最近6条，并保存到PG长期记忆"""
        if len(self._history) < COMPRESS_THRESHOLD:
            return
        keep = 6
        old = self._history[:-keep]
        self._history = self._history[-keep:]

        lines = []
        for m in old:
            role = m.get("role", "")
            content = m.get("content", "")[:300]
            lines.append(f"[{role}]: {content}")
        new_summary = "【历史摘要】\n" + "\n".join(lines)

        # 追加到已有摘要
        if self._history_summary:
            self._history_summary += "\n\n" + new_summary
        else:
            self._history_summary = new_summary

        # 保存摘要到PG长期记忆
        if self._memory:
            import time
            key = f"summary_{int(time.time())}"
            await self._memory._saver.save_fact(self.session_id, key, {"summary": new_summary})
            logger.debug(f"[AgentTeam] 摘要已保存到PG: {key}")

        logger.info(f"[AgentTeam] 历史已压缩，保留最近{keep}条，摘要长度={len(self._history_summary)}")

    # ── 从磁盘读取真实文件结构 ──────────────────────────────

    async def _read_actual_file_tree(self) -> str:
        """从磁盘读取实际文件结构和内容摘要，用于注入 Agent 上下文，防止幻觉"""
        import os, stat

        workspace_dir = os.path.join(self.workspace, self.session_id)
        tasks_base = os.path.abspath("../tasks")

        entries = []

        # 从 .agent_workspace/{session_id}/ 读取
        if os.path.exists(workspace_dir):
            for root, dirs, files in os.walk(workspace_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, workspace_dir)
                    size = os.stat(fp).st_size
                    entries.append(f"[workspace] {rel} ({size} bytes)")

        # 从 tasks/ 读取（按 task_path 精确匹配）
        if self._task_path:
            task_dir = os.path.join(tasks_base, self._task_path)
            if os.path.isdir(task_dir):
                for root, dirs, files in os.walk(task_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        rel = os.path.relpath(fp, task_dir)
                        size = os.stat(fp).st_size
                        entries.append(f"[tasks/{self._task_path}] {rel} ({size} bytes)")

        if not entries:
            return ""

        return "\n".join(sorted(entries))

    async def _read_artifact_file(self, stage_prefix: str) -> str:
        """从 .agent_workspace/{session_id}/ 读取指定阶段的产物文件内容"""
        import os
        artifact_dir = os.path.join(self.workspace, self.session_id)
        if not os.path.isdir(artifact_dir):
            return ""
        for fn in sorted(os.listdir(artifact_dir)):
            if fn.startswith(stage_prefix):
                fp = os.path.join(artifact_dir, fn)
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"[AgentTeam] 读取产物文件失败 {fp}: {e}")
                    return ""
        return ""

    # ── LLM 调用 ──────────────────────────────────────────

    async def _call_agent(self, agent_name: str, extra_context: str = "") -> str:
        # ProductManager 按阶段切换提示词：需求分析 vs 验收
        if agent_name == "ProductManager":
            if self._stage == "architect_review":
                system = PM_PROMPT_ACCEPTANCE
            else:
                system = PM_PROMPT_REQUIREMENTS
        else:
            system = AGENT_PROMPTS[agent_name]

        # 注入历史摘要（防止上下文丢失）
        if self._history_summary:
            system += f"\n\n【历史摘要（供参考）】\n{self._history_summary}"
        # 注入PG长期记忆摘要
        if self._memory:
            long_term = await self._memory.get_long_term_summary()
            if long_term:
                system += f"\n\n【长期记忆摘要】\n{long_term}"

        if extra_context:
            system += f"\n\n【当前上下文补充】\n{extra_context}"

        # 向 Developer 首次调用注入架构师设计文档
        if agent_name == "Developer" and self._dev_passes == 0:
            arch_content = await self._read_artifact_file("02_architecture")
            if arch_content:
                system += f"\n\n【架构师设计文档（请严格遵循此设计实现代码）】\n{arch_content}"

        # ProductManager 在需求分析阶段（stage=init/requirements）不需要工具和文件上下文
        # 只有在验收阶段（stage=architect_review）才需要读取文件
        is_pm_acceptance = agent_name == "ProductManager" and self._stage == "architect_review"

        # Developer / QA / Architect / PM(验收阶段) 需要工具
        if agent_name in ("Developer", "QAEngineer", "Architect") or is_pm_acceptance:
            if self._tools:
                tool_desc = "\n".join(
                    f"- {name}: {fn.__doc__ or ''}" for name, fn in self._tools.items()
                )
                system += f"\n\n【可用工具】\n{tool_desc}"
            if self._task_path:
                system += f"\n\n当前项目路径（task_path）：{self._task_path}"

        # 注入真实文件结构（从磁盘读取），防止幻觉
        # Developer(自检)、QA、Architect(审核)、PM(验收) 需要读取实际文件
        is_acceptance_role = agent_name in ("QAEngineer", "Architect") or is_pm_acceptance
        is_dev_self_review = agent_name == "Developer" and self._dev_passes > 0
        if is_acceptance_role or is_dev_self_review:
            # 向验收角色提供当前已创建的文件列表
            if self._created_files:
                files_list = "\n".join([f"- {f}" for f in self._created_files])
                system += f"\n\n【已创建的文件列表】\n{files_list}"

            # 从磁盘读取实际文件结构
            real_files = await self._read_actual_file_tree()
            if real_files:
                system += f"\n\n【实际文件结构（从磁盘读取，请以此为准）】\n{real_files}"
                if agent_name in ("QAEngineer", "Architect", "ProductManager"):
                    system += (
                        "\n\n⚠️ 重要警告："
                        "\n- 以上【实际文件结构】是从磁盘读取的真实数据"
                        "\n- 你必须使用 file_read 工具读取实际文件内容后再做判断"
                        "\n- 禁止凭空假设或描述文件内容"
                        "\n- 如果未读取文件就下结论，属于严重的幻觉错误"
                    )

            # Developer 自检第二轮
            if agent_name == "Developer" and self._dev_passes > 0:
                system += (
                    "\n\n⚠️ 自检要求（第二轮）："
                    "\n- 这是你之前创建的文件，请使用 file_read 读取它们"
                    "\n- 检查是否有文件只包含骨架/TODO 代码"
                    "\n- 使用 file_write 补充和丰富代码内容（添加完整业务逻辑、错误处理、输入验证）"
                    "\n- 确保所有功能完整实现后再提交"
                )

        # 根据角色调整历史长度和超时时间
        if agent_name == "Developer":
            history_limit = 12
            timeout = 180.0  # Developer 生成文件需要更长时间
        elif agent_name == "QAEngineer":
            history_limit = 12
            timeout = 120.0
        else:
            history_limit = 12
            timeout = 120.0

        messages = [{"role": "system", "content": system}] + self._history[-history_limit:]

        response = await self._llm.chat(
            messages=messages,
            strategy="quality",
            task_id=self.session_id,
            timeout=timeout,
        )
        return response.content

    async def _call_for_sub_team(self, messages: List[Dict], agent_name: str) -> str:
        system = AGENT_PROMPTS.get(agent_name, "")
        full_messages = [{"role": "system", "content": system}] + messages[-10:]
        response = await self._llm.chat(
            messages=full_messages,
            strategy="quality",
            task_id=self.session_id,
        )
        return response.content

    # ── 工具执行 ──────────────────────────────────────────

    async def _execute_tools_in_reply(self, agent_name: str, reply: str) -> str:
        """执行回复中的工具调用（目前仅 Developer）"""
        if agent_name != "Developer":
            return reply
        if not self._tools:
            logger.warning(f"[AgentTeam] Developer 没有可用工具")
            return reply

        results = []

        # 处理 project_create
        m = re.search(r'project_create\s*\(\s*["\']([^"\']+)["\']', reply)
        if m and "project_create" in self._tools:
            try:
                project_name = m.group(1)
                result = await self._tools["project_create"](
                    project_name=project_name, session_id=self.session_id
                )
                logger.debug(f"[AgentTeam] project_create 原始结果: {result}")
                # 尝试从结果中提取 project_name
                project_name_from_result = None
                # 方法1: 解析JSON字符串
                if isinstance(result, str) and result.strip().startswith('{'):
                    import json
                    try:
                        parsed = json.loads(result)
                        if isinstance(parsed, dict):
                            project_name_from_result = parsed.get('project_name')
                    except json.JSONDecodeError:
                        pass
                # 方法2: 正则表达式作为后备
                if not project_name_from_result:
                    tp_match = re.search(r'["\']project_name["\']:\s*["\']([^"\']+)["\']', str(result))
                    if tp_match:
                        project_name_from_result = tp_match.group(1)
                if project_name_from_result:
                    self._task_path = project_name_from_result
                    logger.debug(f"[AgentTeam] 提取 task_path: {self._task_path}")
                results.append(f"✅ 创建项目 '{project_name}'")
            except Exception as e:
                logger.error(f"[AgentTeam] project_create 执行失败: {e}")
                results.append(f"❌ 创建项目失败 '{project_name if 'project_name' in locals() else 'unknown'}': {str(e)[:50]}")
            # 发送项目结构更新事件到前端
            try:
                parsed_result = result
                # 尝试解析JSON字符串
                if isinstance(result, str) and result.strip().startswith('{'):
                    import json
                    try:
                        parsed_result = json.loads(result)
                    except json.JSONDecodeError:
                        parsed_result = None

                if isinstance(parsed_result, dict):
                    project_name = parsed_result.get('project_name', '')
                    files = parsed_result.get('files', [])
                    if project_name:
                        self._emit("project_tree", {
                            "project_name": project_name,
                            "files": files,
                            "file_tree": []  # 可由前端基于 files 列表构建
                        })
            except Exception as e:
                logger.warning(f"[AgentTeam] 发送 project_tree 事件失败: {e}")

        # 处理转义序列的函数
        def unescape(s):
            # 处理常见转义序列
            import re
            # 首先处理双反斜杠
            s = s.replace('\\\\', '\\')
            # 然后处理其他转义序列
            s = re.sub(r'\\n', '\n', s)
            s = re.sub(r'\\t', '\t', s)
            s = re.sub(r'\\r', '\r', s)
            s = re.sub(r'\\"', '"', s)
            s = re.sub(r"\\'", "'", s)
            # 处理Unicode转义序列
            s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
            s = re.sub(r'\\U([0-9a-fA-F]{8})', lambda m: chr(int(m.group(1), 16)), s)
            return s

        # Debug logging
        logger.debug(f"[AgentTeam] Developer reply for file_write extraction: {reply}")
        file_write_pattern = r'file_write\s*\(\s*path\s*=\s*([\'"])([^\'"]*)\1\s*,\s*content\s*=\s*([\'"])(.*?)\3\s*\)'
        for m in re.finditer(file_write_pattern, reply, re.DOTALL):
            logger.debug(f"[AgentTeam] file_write match found: path={m.group(2)}, content={m.group(4)[:50]}")
            try:
                path, content = m.group(2), m.group(4)
                path = unescape(path)
                content = unescape(content)
                logger.debug(f"[AgentTeam] file_write调用: path={path}, task_path={self._task_path}")
                result = await self._tools["file_write"](
                    path=path, content=content,
                    task_path=self._task_path or "",
                    session_id=self.session_id,
                )
                logger.debug(f"[AgentTeam] file_write 返回结果: {result}")
                results.append(f"📄 创建文件 '{path}'")
                # 追踪已创建的文件
                if path not in self._created_files:
                    self._created_files.append(path)
            except Exception as e:
                logger.error(f"[AgentTeam] file_write 执行失败: {e}")
                results.append(f"❌ 创建文件失败 '{path if 'path' in locals() else 'unknown'}': {str(e)[:50]}")
            # 发送文件创建事件到前端
            try:
                parsed_result = result
                # 尝试解析JSON字符串
                if isinstance(result, str) and result.strip().startswith('{'):
                    import json
                    try:
                        parsed_result = json.loads(result)
                    except json.JSONDecodeError:
                        parsed_result = None

                if isinstance(parsed_result, dict):
                    file_path = parsed_result.get('path', '')
                    if file_path:
                        # 提取相对于项目目录的路径
                        rel_path = path  # 已经是相对路径
                        self._emit("files_created", {
                            "files": [{
                                "path": rel_path,
                                "rel_path": rel_path,
                                "project_name": self._task_path or ""
                            }]
                        })
            except Exception as e:
                logger.warning(f"[AgentTeam] 发送 files_created 事件失败: {e}")

        if results:
            tool_summary = "\n".join(results)
            self._emit("tool_result", {"agent": agent_name, "results": tool_summary})
            return reply + f"\n\n【工具执行结果】\n{tool_summary}"

        return reply

    # ── 产物写入 ──────────────────────────────────────────

    async def _maybe_write_artifact(self, agent_name: str, reply: str) -> None:
        m = re.search(r"STAGE_DONE:\s*(\w+)", reply)
        if not m:
            return
        stage = m.group(1)
        action_match = re.search(r"## 行动\n(.*)", reply, re.DOTALL)
        content = action_match.group(1).strip() if action_match else reply
        path = await write_artifact(
            stage=stage, content=content,
            session_id=self.session_id, workspace=self.workspace,
        )
        self._emit("artifact_created", {
            "stage": stage, "agent": agent_name, "path": path,
        })

    # ── 阶段推进 ──────────────────────────────────────────

    def _advance_stage(self, agent_name: str, reply: str) -> Optional[str]:
        if self._done:
            return None

        if "TASK_COMPLETE" in reply:
            return None

        if "HUMAN_INPUT_NEEDED" in reply:
            self._emit("human_input_needed", {"message": reply})
            return None

        m = re.search(r"STAGE_DONE:\s*(\w+)", reply)
        if m:
            stage = m.group(1)

            # Developer 自检：首轮开发后返回自检，二轮后才送 QA
            if stage == "development" and agent_name == "Developer":
                self._dev_passes += 1
                if self._dev_passes >= 2:
                    self._stage = "development_done"
                    self._emit("stage_complete", {
                        "stage": "development_done",
                        "message": "Developer 已完成两轮开发（生成+自检），进入 QA",
                    })
                    return "QAEngineer"
                else:
                    self._stage = "development"
                    self._emit("stage_complete", {
                        "stage": "development_review",
                        "message": "Developer 首轮完成，进入代码自检阶段",
                    })
                    return "Developer"

            self._stage = stage
            next_agent = STAGE_NEXT.get(stage, "Supervisor")
            if next_agent == "__done__":
                # 流程完成，但会话可以继续处理新任务
                self._emit("stage_complete", {"stage": stage, "can_continue": True})
                return None
            return next_agent

        if agent_name == "QAEngineer":
            if "PASS" in reply:
                self._stage = "qa_pass"
                return STAGE_NEXT.get("qa_pass", "ProductManager")
            elif "FAIL" in reply:
                self._qa_retries += 1
                self._dev_passes = 1  # QA 失败后 Developer 只需一轮修复即可
                self._stage = "qa_fail"
                if self._qa_retries >= MAX_QA_RETRIES:
                    self._emit("iteration_limit", {
                        "message": f"QA 已失败 {self._qa_retries} 次，请人工介入"
                    })
                    return None
                self._emit("iteration", {
                    "round": self._qa_retries,
                    "reason": "QA 发现问题，返回 Developer 修复",
                })
                return "Developer"

        # 阶段未推进时，返回当前阶段对应的下一个角色
        if self._stage in STAGE_NEXT:
            next_agent = STAGE_NEXT[self._stage]
            # 防止死循环：如果下一个角色跟当前角色相同且阶段未变化，结束流程
            if next_agent == agent_name:
                logger.warning(f"[AgentTeam] 检测到潜在死循环: {agent_name} 重复调用，终止流程")
                return None
            if next_agent and next_agent != "Supervisor" and next_agent != "__done__":
                return next_agent
            # 如果下一个是Supervisor或__done__，说明流程应该结束了
            if next_agent == "__done__":
                return None
            return None

        return None

    def _get_next_agent_from_stage(self) -> str:
        """根据当前阶段和新任务获取下一个应该继续的角色（用于会话继续场景）"""
        # 验收完成后，新需求应从ProductManager重新开始完整流程
        if self._stage == "acceptance":
            self._stage = "init"  # 重置阶段
            return "ProductManager"

        # 检查上一个agent的回复是否包含STAGE_DONE
        # 如果是，说明已经完成了当前阶段，应该继续推进
        last_reply = ""
        for m in reversed(self._history):
            if m.get("role", "").startswith("[") and "assistant" in m.get("role", ""):
                last_reply = m.get("content", "")
                break

        # 如果上一个agent已经输出了STAGE_DONE，按照STAGE_NEXT推进
        import re
        stage_match = re.search(r"STAGE_DONE:\s*(\w+)", last_reply)
        if stage_match:
            prev_stage = stage_match.group(1)
            if prev_stage in STAGE_NEXT:
                next_in_flow = STAGE_NEXT.get(prev_stage)
                if next_in_flow and next_in_flow != "__done__":
                    return next_in_flow
                elif next_in_flow == "__done__":
                    self._stage = "init"
                    return "ProductManager"

        # 否则根据当前阶段继续
        stage_to_agent = {
            "init": "ProductManager",
            "requirements": "ProductManager",  # 继续需求分析
            "architecture": "Architect",  # 继续架构设计
            "development": "Developer",  # 继续开发
            "qa_pass": "ProductManager",
            "architect_review": "Architect",
            "qa_fail": "Developer",
        }
        return stage_to_agent.get(self._stage, "ProductManager")

    # ── 主循环 ────────────────────────────────────────────

    async def run(self, user_task: str = "", task: str = "", context: Dict[str, Any] = None):
        # 重置状态，支持同一会话中重新执行（中断后二次修改输入等场景）
        self._cancelled = False
        self._done = False

        actual_task = task or user_task
        # 如果不是新会话（已有历史），则追加新任务而不是覆盖
        is_new_session = len(self._history) == 0
        if is_new_session:
            self._emit("start", {"task": actual_task, "session_id": self.session_id})
            self._history.append({"role": "user", "content": actual_task})
            if self._memory:
                await self._memory.add("user", actual_task)
            current_agent = "ProductManager"
        else:
            # 同一会话中继续对话：将新任务追加到历史
            self._history.append({"role": "user", "content": actual_task})
            if self._memory:
                await self._memory.add("user", actual_task)
            # 从当前阶段继续，或回到ProductManager继续分析
            current_agent = self._get_next_agent_from_stage()

        iteration = 0

        while current_agent and iteration < MAX_ITERATIONS:
            if self._cancelled:
                self._emit("stopped", {"message": "任务已被用户中断"})
                break

            # 超过阈值时压缩历史
            if len(self._history) >= COMPRESS_THRESHOLD:
                await self._compress_history()

            iteration += 1
            self._emit("agent_thinking", {
                "agent": current_agent,
                "iteration": iteration,
            })

            try:
                reply = await self._call_agent(current_agent)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[AgentTeam] {current_agent} 调用失败: {e}")
                self._emit("error", {"agent": current_agent, "error": str(e)})
                break

            reply = await self._execute_tools_in_reply(current_agent, reply)
            await self._maybe_write_artifact(current_agent, reply)

            # 提取摘要用于前端展示
            summary = self._extract_reply_summary(reply)
            # 开发者工具调用包含大量代码内容，精简显示版本
            display_reply = self._trim_tool_content(reply) if current_agent == "Developer" else reply
            config = AGENT_CONFIG.get(current_agent, {})
            self._emit("agent_message", {
                "agent": current_agent,
                "content": summary,
                "full_content": display_reply,
                "avatar": config.get("emoji", "🤖"),
                "color": config.get("color", "#f5f5f5"),
                "display_name": config.get("display_name", current_agent),
                "description": config.get("description", ""),
                "iteration": iteration,
            })

            self._history.append({
                "role": "assistant",
                "content": f"[{current_agent}]: {reply}",
            })
            if self._memory:
                await self._memory.add("assistant", reply, agent_name=current_agent)

            sub = parse_sub_team_directive(reply)
            if sub:
                agent_a, agent_b, topic = sub
                discussion = SubTeamDiscussion(
                    agent_a_name=agent_a,
                    agent_b_name=agent_b,
                    topic=topic,
                    llm_caller=self._call_for_sub_team,
                    on_message=self._on_message,
                )
                conclusion = await discussion.run()
                summary_msg = f"[{agent_a}+{agent_b} 讨论结论] {conclusion}"
                self._history.append({"role": "assistant", "content": summary_msg})
                config = AGENT_CONFIG.get(agent_a, {})
                self._emit("agent_message", {
                    "agent": agent_a,
                    "content": conclusion[:200],
                    "full_content": summary_msg,
                    "avatar": config.get("emoji", "🤖"),
                    "color": config.get("color", "#f5f5f5"),
                    "display_name": config.get("display_name", agent_a),
                    "description": config.get("description", ""),
                    "channel": "main",
                })

            current_agent = self._advance_stage(current_agent, reply)

        # 标记完成，阻止后续事件
        self._done = True
        final_summary = self._extract_final_summary()
        self._emit("done", {"summary": final_summary, "iterations": iteration})

        return {
            "success": True,
            "summary": final_summary,
            "iterations": iteration,
            "task_path": self._task_path,
            "session_id": self.session_id,
        }

    def _extract_reply_summary(self, reply: str) -> str:
        """提取回复的摘要：优先取 ## 对话 内容（口语化摘要），其次取 ## 决策 + ## 行动"""
        # 优先取 ## 对话（口语化的角色对话）
        m = re.search(r"## 对话\n(.*?)(?=\n## |\n##$|$)", reply, re.DOTALL)
        if m:
            dialogue = m.group(1).strip()
            if len(dialogue) >= 5:  # 确保对话内容不是太短
                return dialogue

        # 降级：取 ## 决策
        m = re.search(r"## 决策\n(.*?)(?=\n##|$)", reply, re.DOTALL)
        if m:
            decision = m.group(1).strip()
            # 再取 ## 行动 第一句
            action_m = re.search(r"## 行动\n(.*?)(?=\n##|$)", reply, re.DOTALL)
            if action_m:
                action_first = action_m.group(1).strip().split("\n")[0][:150]
                return f"{decision}\n\n{action_first}"
            return decision[:200]

        # 降级：取前200字
        return reply[:200].strip()

    def _extract_final_summary(self) -> str:
        for msg in reversed(self._history):
            content = msg.get("content", "")
            if "[ProductManager]" in content or "[QAEngineer]" in content:
                m = re.search(r"## 行动\n(.*?)(?=\n##|$)", content, re.DOTALL)
                if m:
                    return m.group(1).strip()[:500]
                return content[:500]
        return "任务已完成"

    @staticmethod
    def _trim_tool_content(reply: str) -> str:
        """精简开发者回复中的工具调用内容，省略代码正文仅保留调用信息"""
        import re
        # 替换 file_write 中的 content 参数（支持单引号/双引号/三引号）
        # 处理 content="...大量代码..." 的情况
        result = re.sub(
            r'(file_write\s*\(\s*path\s*=\s*["\'][^"\']+["\']\s*,\s*content\s*=\s*)(["\']{3})(.*?)(\2\s*\))',
            lambda m: m.group(1) + '"""<代码内容已省略>"""\n\t# ...',
            reply,
            flags=re.DOTALL,
        )
        # 处理单行 content="..." 较长的情况
        result = re.sub(
            r'(file_write\s*\(\s*path\s*=\s*["\'][^"\']+["\']\s*,\s*content\s*=\s*)(["\'])(.{100,}?)(\2\s*\))',
            lambda m: m.group(1) + '"<代码内容已省略>"\n\t# ...',
            result,
            flags=re.DOTALL,
        )
        return result
