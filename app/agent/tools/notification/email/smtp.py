"""SMTP 邮件发送器"""

import os
import uuid
from typing import List, Optional, Dict
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header


class EmailSender:
    """邮件发送器"""

    def __init__(self):
        self.smtp_host = os.environ.get("SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
        self.from_email = os.environ.get("EMAILS_FROM_EMAIL", "")
        self.from_name = os.environ.get("EMAILS_FROM_NAME", "AiAgent")

    @property
    def is_configured(self) -> bool:
        """检查是否已配置"""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    async def send(
        self,
        to: List[str],
        subject: str,
        content: str,
        html: bool = False,
        attachments: Optional[List[Dict[str, bytes]]] = None
    ) -> str:
        """发送邮件"""
        if not self.is_configured:
            raise Exception("SMTP 未配置")

        message = MIMEMultipart("alternative")
        message["Message-ID"] = f"<{uuid.uuid4()}@{self.smtp_host}>"
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = ", ".join(to)
        message["Subject"] = Header(subject, "utf-8")

        content_type = "html" if html else "plain"
        message.attach(MIMEText(content, content_type, "utf-8"))

        if attachments:
            for attachment in attachments:
                for filename, data in attachment.items():
                    part = MIMEText(data.decode("utf-8") if isinstance(data, bytes) else data)
                    part.add_header("Content-Disposition", "attachment", filename=filename)
                    message.attach(part)

        try:
            if self.use_tls:
                await aiosmtplib.send(
                    message,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_user,
                    password=self.smtp_password,
                    start_tls=True,
                )
            else:
                await aiosmtplib.send(
                    message,
                    hostname=self.smtp_host,
                    port=self.smtp_port,
                    username=self.smtp_user,
                    password=self.smtp_password,
                )

            return message["Message-ID"]
        except Exception as e:
            raise Exception(f"邮件发送失败: {e}")

    async def send_template(
        self,
        to: List[str],
        subject: str,
        template_name: str,
        template_data: Dict[str, str]
    ) -> str:
        """使用模板发送邮件"""
        template_content = self._get_template(template_name, template_data)
        return await self.send(to=to, subject=subject, content=template_content, html=True)

    def _get_template(self, template_name: str, data: Dict[str, str]) -> str:
        """获取邮件模板"""
        templates = {
            "task_complete": """
            <html>
            <body>
                <h2>任务完成通知</h2>
                <p>您好，</p>
                <p>您的任务已完成:</p>
                <ul>
                    <li><strong>任务名称:</strong> {task_name}</li>
                    <li><strong>完成时间:</strong> {completed_at}</li>
                </ul>
                <p><strong>结果:</strong></p>
                <pre>{result}</pre>
            </body>
            </html>
            """,
            "error_alert": """
            <html>
            <body>
                <h2 style="color: red;">错误告警</h2>
                <p>您好，</p>
                <p>系统检测到以下错误:</p>
                <ul>
                    <li><strong>错误类型:</strong> {error_type}</li>
                    <li><strong>发生时间:</strong> {error_time}</li>
                </ul>
                <p><strong>错误详情:</strong></p>
                <pre>{error_message}</pre>
            </body>
            </html>
            """,
        }

        template = templates.get(template_name, "")
        return template.format(**data)
