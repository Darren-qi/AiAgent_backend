"""输入安全检查"""

import os
import re


class InputGuard:
    """输入安全检查器"""

    def __init__(self):
        self.max_length = int(os.environ.get("INPUT_MAX_LENGTH", "100000"))

        forbidden_str = os.environ.get("FORBIDDEN_COMMANDS", "rm -rf,shutdown,reboot,mkfs")
        self.forbidden_commands = [cmd.strip() for cmd in forbidden_str.split(",") if cmd.strip()]

        dangerous_str = os.environ.get("DANGEROUS_KEYWORDS", "")
        self.dangerous_keywords = [kw.strip() for kw in dangerous_str.split(",") if kw.strip()]

    def check(self, content: str) -> tuple[bool, str | None]:
        """
        检查输入内容的安全性

        Returns:
            (is_safe, error_message)
        """
        if not content:
            return True, None

        if len(content) > self.max_length:
            return False, f"输入内容过长，最大允许 {self.max_length} 字符"

        content_lower = content.lower()

        for keyword in self.dangerous_keywords:
            if keyword.lower() in content_lower:
                return False, f"内容包含禁止关键词: {keyword}"

        for command in self.forbidden_commands:
            if command.lower() in content_lower:
                return False, f"内容包含禁止命令: {command}"

        # 2026-11-10：移除 SQL 注入/XSS 正则穷举检查（误杀实证：任务含 Markdown '#'
        # 或英文 CREATE/UPDATE 等词即判"SQL 注入"，线上任务报错根因之一）。
        # 任务文本是数据不是 SQL/HTML：入库参数化（pgsaver）、前端 Vue 默认转义。
        # 保留长度上限与危险命令拦截；_check_sql_injection/_check_xss 留给测试。
        return True, None

    def _check_sql_injection(self, content: str) -> bool:
        """检测 SQL 注入"""
        sql_patterns = [
            r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION)\b)",
            r"(--|#|/\*|\*/)",
            r"(\bOR\b.*=.*\bOR\b)",
            r"(\bAND\b.*=.*\bAND\b)",
        ]

        for pattern in sql_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def _check_xss(self, content: str) -> bool:
        """检测 XSS 攻击"""
        xss_patterns = [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"onerror\s*=",
            r"onclick\s*=",
            r"onload\s*=",
        ]

        for pattern in xss_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def sanitize(self, content: str) -> str:
        """清理危险内容"""
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"javascript:", "", content, flags=re.IGNORECASE)
        content = re.sub(r"on\w+\s*=", "", content, flags=re.IGNORECASE)
        return content
