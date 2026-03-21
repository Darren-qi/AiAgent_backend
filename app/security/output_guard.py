"""输出安全检查"""

import re
from typing import Optional


class OutputGuard:
    """输出安全检查器"""

    def __init__(self):
        self.sensitive_patterns = [
            r"api[_-]?key['\"]?\s*[:=]\s*['\"]?[\w-]+",
            r"password['\"]?\s*[:=]\s*['\"]?[\w!@#$%^&*()]+",
            r"secret['\"]?\s*[:=]\s*['\"]?[\w-]+",
            r"token['\"]?\s*[:=]\s*['\"]?[\w.-]+",
            r"sk-[\w]+",
            r"ak-[\w]+",
        ]

    def check(self, content: str) -> tuple[bool, Optional[str]]:
        """
        检查输出内容是否包含敏感信息

        Returns:
            (is_safe, warning_message)
        """
        if not content:
            return True, None

        for pattern in self.sensitive_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return False, f"输出可能包含敏感信息: {match.group()[:20]}..."

        return True, None

    def mask_sensitive(self, content: str) -> str:
        """遮蔽敏感信息"""
        masked = content

        masked = re.sub(r"sk-[\w]+", "[API_KEY_MASKED]", masked, flags=re.IGNORECASE)
        masked = re.sub(r"ak-[\w]+", "[API_KEY_MASKED]", masked, flags=re.IGNORECASE)
        masked = re.sub(
            r"(password|secret|token|api_key)\s*[:=]\s*['\"]?([\w!@#$%^&*()-]+)",
            r"\1: [MASKED]",
            masked,
            flags=re.IGNORECASE
        )

        return masked

    def sanitize_html(self, content: str) -> str:
        """清理 HTML"""
        content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"<iframe[^>]*>.*?</iframe>", "", content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r"on\w+\s*=\s*['\"][^'\"]*['\"]", "", content, flags=re.IGNORECASE)
        return content
