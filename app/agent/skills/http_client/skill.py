"""HTTP Client Skill - HTTP 客户端技能"""

import httpx
from typing import Dict, Any

from app.agent.skills.core.base_skill import BaseSkill, SkillResult


class HTTPClientSkill(BaseSkill):
    """HTTP 客户端 Skill"""

    DEFAULT_PARAMETERS = [
        {"name": "url", "type": "string", "required": True, "description": "请求 URL"},
        {"name": "method", "type": "string", "required": False, "description": "请求方法 GET/POST", "default": "GET"},
        {"name": "headers", "type": "object", "required": False, "description": "请求头"},
        {"name": "timeout", "type": "number", "required": False, "description": "超时时间(秒)", "default": 120},
    ]

    def __init__(self):
        super().__init__()
        self.name = "http_client"
        self.description = "发起 HTTP 请求获取网页内容"
        self.parameters = self.DEFAULT_PARAMETERS

    async def execute(self, **kwargs) -> SkillResult:
        url = kwargs.get("url")
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {})
        timeout = kwargs.get("timeout", 120)

        if not url:
            return SkillResult(success=False, error="缺少 url 参数")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=kwargs.get("data"))
                elif method == "PUT":
                    response = await client.put(url, headers=headers, json=kwargs.get("data"))
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    return SkillResult(success=False, error=f"不支持的请求方法: {method}")

                return SkillResult(
                    success=True,
                    data={"status": response.status_code, "content": response.text[:5000]},
                    metadata={"url": url, "method": method}
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))


# 导出执行入口
skill = HTTPClientSkill()


async def execute(**kwargs) -> SkillResult:
    """Skill 执行入口"""
    return await skill.execute(**kwargs)
