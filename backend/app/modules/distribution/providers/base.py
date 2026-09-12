"""DistributionProvider: one interface every social platform implements.
Only YouTube ships wired to a real API in this codebase — Instagram/
Facebook/X/LinkedIn each require their own developer-app review and business
verification that CreatorOS cannot obtain autonomously, so they ship as
NotConfiguredProvider until a human completes that per-platform setup (see
docs/youtube.md and docs/FINAL_AUDIT.md)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class DistributionProviderError(Exception):
    pass


@dataclass
class PublishResult:
    platform_post_id: str
    status: str


@dataclass
class PlatformMetrics:
    views: int | None
    engagement: int | None
    clicks: int | None
    attribution_quality: str  # DIRECT | ATTRIBUTED | ESTIMATED | UNAVAILABLE


class DistributionProvider(ABC):
    name: str

    @abstractmethod
    async def connect(self, auth_code: str) -> None: ...

    @abstractmethod
    async def validate(self, asset: dict) -> list[str]:
        """Returns a list of validation problems; empty list means valid."""

    @abstractmethod
    async def prepare(self, asset: dict) -> dict: ...

    @abstractmethod
    async def publish(self, asset: dict) -> PublishResult: ...

    @abstractmethod
    async def schedule(self, asset: dict, publish_at) -> PublishResult: ...

    @abstractmethod
    async def status(self, platform_post_id: str) -> str: ...

    @abstractmethod
    async def metrics(self, platform_post_id: str) -> PlatformMetrics: ...

    @abstractmethod
    async def disconnect(self) -> None: ...


class NotConfiguredProvider(DistributionProvider):
    """Placeholder for a platform whose OAuth app has not been authorized yet.
    Every method raises rather than silently no-opping, so callers can't
    mistake "not configured" for "published successfully"."""

    def __init__(self, platform_name: str):
        self.name = platform_name

    def _unavailable(self):
        raise DistributionProviderError(
            f"{self.name} is not configured. This requires completing that "
            f"platform's developer app review and OAuth setup — see docs/youtube.md."
        )

    async def connect(self, auth_code: str) -> None:
        self._unavailable()

    async def validate(self, asset: dict) -> list[str]:
        return [f"{self.name} is not configured"]

    async def prepare(self, asset: dict) -> dict:
        self._unavailable()

    async def publish(self, asset: dict) -> PublishResult:
        self._unavailable()

    async def schedule(self, asset: dict, publish_at) -> PublishResult:
        self._unavailable()

    async def status(self, platform_post_id: str) -> str:
        self._unavailable()

    async def metrics(self, platform_post_id: str) -> PlatformMetrics:
        self._unavailable()

    async def disconnect(self) -> None:
        return None
