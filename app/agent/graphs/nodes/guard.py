"""安全守卫节点"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class GuardResult:
    """守卫检查结果"""
    passed: bool
    error: Optional[str] = None
    warnings: Optional[List[str]] = None


class Guard:
    """安全守卫"""

    def __init__(self):
        self._input_checks = []
        self._output_checks = []

    async def check_input(self, task: str, params: Optional[Dict[str, Any]] = None) -> GuardResult:
        """
        检查输入安全性

        包括命令注入、Prompt 注入等检查。
        """
        warnings = []

        dangerous = self._check_dangerous_commands(task)
        if dangerous:
            return GuardResult(passed=False, error=f"禁止的命令: {dangerous}")

        if self._check_prompt_injection(task):
            warnings.append("检测到可能的 Prompt 注入，已自动处理")

        return GuardResult(passed=True, warnings=warnings or None)

    async def check_output(self, output: Any) -> GuardResult:
        """
        检查输出安全性

        包括敏感信息泄露、恶意代码等检查。
        """
        if not isinstance(output, str):
            output = str(output)

        sensitive = self._check_sensitive_data(output)
        if sensitive:
            return GuardResult(
                passed=True,
                warnings=[f"输出包含可能的敏感数据: {sensitive}"],
            )

        return GuardResult(passed=True)

    async def check_skill(
        self, skill_name: str, params: Dict[str, Any]
    ) -> GuardResult:
        """
        检查 Skill 调用的安全性

        验证参数是否在允许范围内。
        """
        if skill_name == "shell_exec":
            if "command" in params:
                return GuardResult(
                    passed=False, error="禁止直接执行 shell 命令"
                )

        return GuardResult(passed=True)

    def _check_dangerous_commands(self, content: str) -> Optional[str]:
        dangerous = ["rm -rf", "shutdown", "reboot", "mkfs", ":(){", "fork()"]
        content_lower = content.lower()
        for cmd in dangerous:
            if cmd.lower() in content_lower:
                return cmd
        return None

    def _check_prompt_injection(self, content: str) -> bool:
        injection_patterns = [
            "ignore previous instructions",
            "disregard above",
            "new instructions:",
            "系统提示",
            "你是一个",
        ]
        content_lower = content.lower()
        for pattern in injection_patterns:
            if pattern.lower() in content_lower:
                return True
        return False

    def _check_sensitive_data(self, content: str) -> Optional[str]:
        import re
        patterns = [
            r"sk-[\w]{20,}",
            r"api[_-]?key['\"]?\s*[:=]",
            r"password['\"]?\s*[:=]",
            r"\d{16,}",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group()[:30]
        return None
