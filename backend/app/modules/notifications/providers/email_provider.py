import smtplib
from email.mime.text import MIMEText

from app.core.config import Settings
from app.modules.notifications.providers.base import NotificationProvider, NotificationProviderError


class SmtpEmailProvider(NotificationProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, title: str, body: str) -> None:
        if not self._settings.smtp_host:
            raise NotificationProviderError("SMTP is not configured (SMTP_HOST missing)")

        msg = MIMEText(body)
        msg["Subject"] = title
        msg["From"] = self._settings.smtp_from
        msg["To"] = to

        try:
            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=10) as server:
                server.starttls()
                if self._settings.smtp_user:
                    server.login(self._settings.smtp_user, self._settings.smtp_password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationProviderError(f"Failed to send email: {exc}") from exc
