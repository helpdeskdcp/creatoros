from app.core.config import Settings, get_settings
from app.modules.billing.providers.base import NullPaymentProvider, PaymentProvider


def get_payment_provider(settings: Settings | None = None) -> PaymentProvider:
    settings = settings or get_settings()
    if settings.billing_provider == "stripe":
        raise NotImplementedError(
            "billing_provider=stripe is selected but no StripePaymentProvider exists yet -- "
            "implementing PaymentProvider for a real processor is the only change needed "
            "once real credentials are available."
        )
    return NullPaymentProvider()
