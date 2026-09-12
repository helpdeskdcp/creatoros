import httpx

from app.core.config import Settings
from app.modules.notifications.providers.base import NotificationProvider, NotificationProviderError


class TelegramProvider(NotificationProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, title: str, body: str) -> None:
        if not self._settings.telegram_bot_token:
            raise NotificationProviderError("Telegram is not configured (TELEGRAM_BOT_TOKEN missing)")

        chat_id = to or self._settings.telegram_chat_id
        url = f"https://api.telegram.org/bot{self._settings.telegram_bot_token}/sendMessage"
        text = f"*{title}*\n{body}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
        except httpx.TransportError as exc:
            raise NotificationProviderError(f"Telegram API unreachable: {exc}") from exc

        if resp.status_code != 200:
            raise NotificationProviderError(f"Telegram API returned {resp.status_code}: {resp.text}")
