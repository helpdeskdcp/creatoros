from app.modules.notifications.providers.base import NotificationProvider


class InAppProvider(NotificationProvider):
    """No-op delivery: the row already exists in the notifications table by
    the time send() is called, and the frontend polls/reads it directly."""

    async def send(self, *, to: str, title: str, body: str) -> None:
        return None
