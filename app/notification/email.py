"""邮件通知服务"""

from typing import List, Dict, Any, Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailNotifier:
    """邮件通知器"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_address: str,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.use_tls = use_tls

    async def send(
        self,
        to_addresses: List[str],
        subject: str,
        content: str,
        content_type: str = "plain",
    ) -> Dict[str, Any]:
        """发送邮件"""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.from_address
            msg["To"] = ", ".join(to_addresses)
            msg["Subject"] = subject
            msg.attach(MIMEText(content, content_type, "utf-8"))

            if self.use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.from_address, to_addresses, msg.as_string())
            server.quit()

            return {"success": True, "message": "Email sent successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def send_html(
        self,
        to_addresses: List[str],
        subject: str,
        html_content: str,
    ) -> Dict[str, Any]:
        """发送 HTML 邮件"""
        return await self.send(to_addresses, subject, html_content, "html")

    async def send_template(
        self,
        to_addresses: List[str],
        subject: str,
        template: str,
        variables: Dict[str, str],
    ) -> Dict[str, Any]:
        """使用模板发送邮件"""
        content = template
        for key, value in variables.items():
            content = content.replace(f"{{{{{key}}}}}", value)
        return await self.send(to_addresses, subject, content, "html")
