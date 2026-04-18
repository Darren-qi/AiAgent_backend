"""Agent 测试"""

import pytest
from app.agent.graphs.main_graph import AgentGraph
from app.agent.memory.manager import MemoryManager
from app.security.input_guard import InputGuard
from app.security.output_guard import OutputGuard


class TestAgentGraph:
    """Agent 图测试"""

    @pytest.mark.asyncio
    async def test_execute_simple_task(self):
        """测试简单任务执行"""
        graph = AgentGraph()
        result = await graph.execute(task="说 hello")
        assert "success" in result
        assert "intent" in result

    @pytest.mark.asyncio
    async def test_execute_with_context(self):
        """测试带上下文的执行"""
        graph = AgentGraph()
        result = await graph.execute(
            task="测试",
            context={"user_id": "test"}
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_creates_flask_blog(self):
        """测试创建 Flask 博客项目任务"""
        graph = AgentGraph()
        result = await graph.execute(
            task="创建一个Flask博客项目",
            context={"user_id": "test_user", "session_id": "test_flask_session"}
        )
        # 必须包含 success 字段
        assert "success" in result
        # 必须有 result 字段，不能是 None
        assert result.get("result") is not None, "result 不应为 None"
        # 不应该返回"任务已完成，但没有返回结果"
        result_str = str(result.get("result", ""))
        assert "任务已完成，但没有返回结果" not in result_str, f"result 内容异常: {result_str}"
        # 应该返回有意义的结果内容
        assert len(result_str) > 0, "result 不应为空字符串"


class TestMemoryManager:
    """记忆管理器测试"""

    def test_create_memory_manager(self):
        """测试创建记忆管理器"""
        manager = MemoryManager(session_id="test_session")
        assert manager.session_id == "test_session"

    @pytest.mark.asyncio
    async def test_add_messages(self):
        """测试添加消息"""
        manager = MemoryManager(session_id="test")
        await manager.add_user_message("你好")
        await manager.add_assistant_message("你好，有什么可以帮你的？")

        history = manager.get_conversation_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_get_context_for_llm(self):
        """测试获取 LLM 上下文"""
        manager = MemoryManager(session_id="test")
        await manager.add_user_message("你好")
        await manager.add_assistant_message("你好！")

        context = manager.get_context_for_llm()
        assert len(context) == 2


class TestInputGuard:
    """输入安全检查测试"""

    def test_normal_content(self):
        """测试正常内容"""
        guard = InputGuard()
        is_safe, error = guard.check("这是一个正常的测试内容")
        assert is_safe is True
        assert error is None

    def test_empty_content(self):
        """测试空内容"""
        guard = InputGuard()
        is_safe, error = guard.check("")
        assert is_safe is True

    def test_too_long_content(self):
        """测试过长内容"""
        guard = InputGuard()
        long_content = "a" * 200000
        is_safe, error = guard.check(long_content)
        assert is_safe is False
        assert "过长" in error

    def test_sql_injection(self):
        """测试 SQL 注入检测"""
        guard = InputGuard()
        sql = "SELECT * FROM users WHERE id=1"
        is_safe, error = guard.check(sql)
        assert is_safe is False

    def test_xss_attack(self):
        """测试 XSS 攻击检测"""
        guard = InputGuard()
        xss = "<script>alert('xss')</script>"
        is_safe, error = guard.check(xss)
        assert is_safe is False

    def test_sanitize(self):
        """测试内容清理"""
        guard = InputGuard()
        content = "<script>alert('xss')</script>"
        sanitized = guard.sanitize(content)
        assert "<script>" not in sanitized


class TestOutputGuard:
    """输出安全检查测试"""

    def test_normal_content(self):
        """测试正常内容"""
        guard = OutputGuard()
        is_safe, warning = guard.check("这是一个正常的输出")
        assert is_safe is True

    def test_api_key_detection(self):
        """测试 API Key 检测"""
        guard = OutputGuard()
        content = "api_key: sk-1234567890abcdef"
        is_safe, warning = guard.check(content)
        assert is_safe is False
        assert warning is not None

    def test_mask_sensitive(self):
        """测试敏感信息遮蔽"""
        guard = OutputGuard()
        content = "password: mysecretpassword"
        masked = guard.mask_sensitive(content)
        assert "mysecretpassword" not in masked
        assert "MASKED" in masked
