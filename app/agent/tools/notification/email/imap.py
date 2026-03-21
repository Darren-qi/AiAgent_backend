"""IMAP 邮件接收器"""

import os
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import imaplib
import email
from email.header import decode_header


@dataclass
class EmailMessage:
    """邮件消息"""
    message_id: str
    subject: str
    from_address: str
    to_addresses: List[str]
    date: str
    body: str
    html_body: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None


class EmailReceiver:
    """IMAP 邮件接收器"""

    def __init__(self):
        self.imap_host = os.environ.get("IMAP_HOST", "")
        self.imap_port = int(os.environ.get("IMAP_PORT", "993"))
        self.imap_user = os.environ.get("IMAP_USER", "")
        self.imap_password = os.environ.get("IMAP_PASSWORD", "")
        self.use_ssl = os.environ.get("IMAP_USE_SSL", "true").lower() == "true"

    @property
    def is_configured(self) -> bool:
        """检查是否已配置"""
        return bool(self.imap_host and self.imap_user and self.imap_password)

    def _decode_header(self, header_value: str) -> str:
        """解码邮件头"""
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                charset = charset or "utf-8"
                result.append(part.decode(charset, errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def connect(self):
        """连接 IMAP 服务器"""
        if not self.is_configured:
            raise Exception("IMAP 未配置")

        if self.use_ssl:
            return imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        else:
            return imaplib.IMAP4(self.imap_host, self.imap_port)

    async def fetch_unread(self, folder: str = "INBOX", limit: int = 10) -> List[EmailMessage]:
        """获取未读邮件"""
        try:
            mail = self.connect()
            mail.login(self.imap_user, self.imap_password)
            mail.select(folder)

            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                return []

            email_ids = messages[0].split()[-limit:]

            results = []
            for email_id in email_ids:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                body = ""
                html_body = None
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    elif part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode("utf-8", errors="replace")

                results.append(EmailMessage(
                    message_id=msg.get("Message-ID", ""),
                    subject=self._decode_header(msg.get("Subject", "")),
                    from_address=self._decode_header(msg.get("From", "")),
                    to_addresses=self._decode_header(msg.get("To", "")).split(", "),
                    date=msg.get("Date", ""),
                    body=body,
                    html_body=html_body,
                ))

            mail.logout()
            return results
        except Exception as e:
            raise Exception(f"获取邮件失败: {e}")

    async def process_commands(self, callback) -> List[Dict[str, Any]]:
        """处理邮件中的命令"""
        messages = await self.fetch_unread()
        results = []

        for msg in messages:
            if "command:" in msg.body.lower():
                lines = msg.body.split("\n")
                command = None
                for line in lines:
                    if line.lower().startswith("command:"):
                        command = line.split(":", 1)[1].strip()
                        break

                if command:
                    result = await callback(command, msg)
                    results.append({
                        "message_id": msg.message_id,
                        "command": command,
                        "result": result,
                    })

        return results
