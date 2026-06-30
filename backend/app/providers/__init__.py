from app.core.config import settings
from app.providers.base import FareProvider


def get_provider() -> FareProvider:
    """Return the configured fare provider (mock or amadeus)."""
    if settings.FARE_PROVIDER == "amadeus":
        from app.providers.amadeus import AmadeusProvider
        return AmadeusProvider()
    from app.providers.mock import MockProvider
    return MockProvider()
