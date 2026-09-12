from abc import ABC, abstractmethod


class NotificationProviderError(Exception):
    pass


class NotificationProvider(ABC):
    @abstractmethod
    async def send(self, *, to: str, title: str, body: str) -> None: ...
