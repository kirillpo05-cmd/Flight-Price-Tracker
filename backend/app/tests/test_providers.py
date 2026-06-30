"""Tests for provider module (SPEC.md §3)."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.providers.base import Offer, SearchParams
from app.providers.mock import MockProvider


@pytest.fixture
def params() -> SearchParams:
    return SearchParams(
        origin="RIX",
        destination="BCN",
        depart_date=date(2025, 9, 15),
        passengers=1,
        cabin="economy",
    )


class TestMockProvider:
    def test_returns_offers(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        assert len(offers) >= 3
        assert all(isinstance(o, Offer) for o in offers)

    def test_sorted_by_price(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        prices = [o.price for o in offers]
        assert prices == sorted(prices)

    def test_deterministic_exact_mode(self, params: SearchParams) -> None:
        a = MockProvider().search(params)
        b = MockProvider().search(params)
        assert [o.price for o in a] == [o.price for o in b]

    def test_price_in_reasonable_range(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        for o in offers:
            assert 30.0 <= o.price <= 500.0

    def test_utc_datetimes(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        for o in offers:
            assert o.depart_at.tzinfo == timezone.utc
            assert o.arrive_at.tzinfo == timezone.utc

    def test_arrive_after_depart(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        for o in offers:
            assert o.arrive_at > o.depart_at

    def test_duration_matches_times(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        for o in offers:
            computed = int((o.arrive_at - o.depart_at).total_seconds() // 60)
            assert computed == o.duration_min

    def test_different_routes_different_price(self) -> None:
        p1 = SearchParams("RIX", "BCN", date(2025, 9, 15), 1, "economy")
        p2 = SearchParams("WAW", "LHR", date(2025, 9, 15), 1, "economy")
        o1 = MockProvider().search(p1)
        o2 = MockProvider().search(p2)
        assert o1[0].price != o2[0].price

    def test_range_mode_varies_between_calls(self) -> None:
        """Range mode uses random date selection — prices may differ between calls."""
        prices_seen: set[float] = set()
        p = SearchParams(
            "RIX", "BCN",
            depart_date=date(2025, 9, 1),
            passengers=1,
            cabin="economy",
            date_to=date(2025, 9, 30),
        )
        for _ in range(10):
            offers = MockProvider().search(p)
            prices_seen.add(offers[0].price)
        # With a 30-day range, at least some calls should pick different dates
        assert len(prices_seen) > 1

    def test_airlines_known_codes(self, params: SearchParams) -> None:
        allowed = {"W6", "VY", "FR"}
        offers = MockProvider().search(params)
        for o in offers:
            assert o.airline in allowed

    def test_raw_id_unique(self, params: SearchParams) -> None:
        offers = MockProvider().search(params)
        ids = [o.raw_id for o in offers]
        assert len(ids) == len(set(ids))


class TestGetProvider:
    def test_returns_mock_by_default(self) -> None:
        from app.providers import get_provider
        from app.providers.mock import MockProvider

        with patch("app.providers.settings") as mock_settings:
            mock_settings.FARE_PROVIDER = "mock"
            provider = get_provider()
        assert isinstance(provider, MockProvider)

    def test_returns_amadeus_when_configured(self) -> None:
        from app.providers import get_provider
        from app.providers.amadeus import AmadeusProvider

        with (
            patch("app.providers.settings") as mock_settings,
            patch("app.providers.amadeus.settings") as amadeus_settings,
        ):
            mock_settings.FARE_PROVIDER = "amadeus"
            amadeus_settings.AMADEUS_CLIENT_ID = "test_id"
            amadeus_settings.AMADEUS_CLIENT_SECRET = "test_secret"
            amadeus_settings.REDIS_URL = "redis://localhost:6379/0"
            with patch("app.providers.amadeus.sync_redis.from_url"), \
                 patch("app.providers.amadeus.httpx.Client"):
                provider = get_provider()
        assert isinstance(provider, AmadeusProvider)
