"""内置 Skill - HTTP 客户端"""

import httpx
from typing import Dict, Any, Optional

from app.agent.skills.base import BaseSkill, SkillResult


class HTTPClientSkill(BaseSkill):
    """HTTP 客户端 Skill"""

    def __init__(self):
        super().__init__()
        self.name = "http_client"
        self.description = "发起 HTTP 请求获取网页内容"
        self.parameters = [
            {"name": "url", "type": "string", "required": True, "description": "请求 URL"},
            {"name": "method", "type": "string", "required": False, "description": "请求方法 GET/POST"},
            {"name": "headers", "type": "object", "required": False, "description": "请求头"},
            {"name": "timeout", "type": "number", "required": False, "description": "超时时间(秒)"},
        ]

    async def execute(self, **kwargs) -> SkillResult:
        url = kwargs.get("url")
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {})
        timeout = kwargs.get("timeout", 30)

        if not url:
            return SkillResult(success=False, error="缺少 url 参数")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=kwargs.get("data"))
                else:
                    return SkillResult(success=False, error=f"不支持的请求方法: {method}")

                return SkillResult(
                    success=True,
                    data={"status": response.status_code, "content": response.text[:5000]},
                    metadata={"url": url, "method": method}
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))
