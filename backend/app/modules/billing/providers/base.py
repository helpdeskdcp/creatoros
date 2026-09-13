"""PaymentProvider: same interface pattern as every other external
integration in this codebase (AIProvider, YouTubeProvider, StorageBackend,
TranscriptionProvider, DistributionProvider) -- one interface, and a
NullPaymentProvider that reports CONFIGURATION_REQUIRED honestly rather
than faking a successful charge. A real StripePaymentProvider can be
added later implementing this same interface without touching
billing.service."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class PaymentProviderError(Exception):
    pass


class PaymentProviderNotConfiguredError(PaymentProviderError):
    """Distinct from a real payment failure -- this means no payment
    provider is set up at all, not that a charge was attempted and
    declined."""


@dataclass
class CheckoutSession:
    checkout_url: str
    external_session_id: str


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    async def create_checkout_session(self, organization_id: str, plan: str, success_url: str) -> CheckoutSession: ...

    @abstractmethod
    async def get_subscription_status(self, external_subscription_id: str) -> str: ...

    @abstractmethod
    async def cancel_subscription(self, external_subscription_id: str) -> None: ...


class NullPaymentProvider(PaymentProvider):
    """The only PaymentProvider CreatorOS ships with today -- no payment
    processor credentials are configured. Every method reports
    CONFIGURATION_REQUIRED explicitly; none of them silently succeeds or
    fabricates a subscription."""

    name = "none"

    async def create_checkout_session(self, organization_id: str, plan: str, success_url: str) -> CheckoutSession:
        raise PaymentProviderNotConfiguredError(
            "No payment provider is configured. Set BILLING_PROVIDER and its credentials "
            "to enable real checkout (see docs/)."
        )

    async def get_subscription_status(self, external_subscription_id: str) -> str:
        raise PaymentProviderNotConfiguredError("No payment provider is configured.")

    async def cancel_subscription(self, external_subscription_id: str) -> None:
        raise PaymentProviderNotConfiguredError("No payment provider is configured.")
