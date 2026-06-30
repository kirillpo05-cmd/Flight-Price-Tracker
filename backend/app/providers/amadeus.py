import logging
import time
from datetime import datetime, timezone

import httpx
import redis as sync_redis

from app.core.config import settings
from app.providers.base import (
    FareProvider,
    Offer,
    ProviderError,
    ProviderTimeout,
    SearchParams,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.amadeus.com"
_TOKEN_KEY = "amadeus:access_token"
_RPS_KEY = "amadeus:rps"
_MAX_RPS = 9
_REQUEST_TIMEOUT = 5.0

_CABIN_MAP = {
    "economy": "ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST_CLASS",
}

_RETRY_DELAYS = [1, 2, 4]  # seconds between attempts (4 total attempts)


class ConfigError(Exception):
    pass


class AmadeusProvider(FareProvider):
    """Live Amadeus Flight Offers Search v2 provider.

    Token cached in Redis (amadeus:access_token) with TTL = expires_in - 60s.
    Rate-limited to MAX_RPS via Redis counter with 1s TTL.
    Retries up to 3 times with exponential backoff on ProviderTimeout / ProviderError.
    """

    def __init__(self) -> None:
        if not settings.AMADEUS_CLIENT_ID or not settings.AMADEUS_CLIENT_SECRET:
            raise ConfigError(
                "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set in environment"
            )
        self._redis = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._http = httpx.Client(timeout=_REQUEST_TIMEOUT)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self) -> str:
        token = self._redis.get(_TOKEN_KEY)
        if token:
            return token

        try:
            resp = self._http.post(
                f"{_BASE_URL}/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.AMADEUS_CLIENT_ID,
                    "client_secret": settings.AMADEUS_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Amadeus auth timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Amadeus auth failed: HTTP {exc.response.status_code}") from exc

        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 1799))
        self._redis.set(_TOKEN_KEY, token, ex=max(1, expires_in - 60))
        return token

    # ------------------------------------------------------------------
    # Rate limiter
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        count = self._redis.incr(_RPS_KEY)
        if count == 1:
            self._redis.expire(_RPS_KEY, 1)
        if count > _MAX_RPS:
            time.sleep(0.1)

    # ------------------------------------------------------------------
    # Single request (no retry)
    # ------------------------------------------------------------------

    def _request(self, params: SearchParams, token: str) -> list[Offer]:
        self._rate_limit()

        query: dict = {
            "originLocationCode": params.origin,
            "destinationLocationCode": params.destination,
            "departureDate": params.depart_date.isoformat(),
            "adults": params.passengers,
            "travelClass": _CABIN_MAP[params.cabin],
            "max": 10,
            "currencyCode": params.currency,
        }
        if params.return_date:
            query["returnDate"] = params.return_date.isoformat()

        try:
            resp = self._http.get(
                f"{_BASE_URL}/v2/shopping/flight-offers",
                params=query,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("Amadeus search timed out") from exc

        if resp.status_code == 401:
            self._redis.delete(_TOKEN_KEY)
            raise ProviderError("amadeus_token_expired")

        if resp.status_code == 429:
            raise ProviderError("amadeus_rate_limit")

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Amadeus HTTP {exc.response.status_code}") from exc

        return self._parse(resp.json())

    # ------------------------------------------------------------------
    # Response normalisation
    # ------------------------------------------------------------------

    def _parse(self, data: dict) -> list[Offer]:
        offers: list[Offer] = []
        for item in data.get("data", []):
            try:
                price = float(item["price"]["grandTotal"])
                if item["price"].get("currency", "EUR") != "EUR":
                    logger.warning(
                        "Amadeus returned non-EUR offer (currency=%s), skipping",
                        item["price"].get("currency"),
                    )
                    continue

                itinerary = item["itineraries"][0]
                segments = itinerary["segments"]
                first_seg = segments[0]
                last_seg = segments[-1]

                depart_at = _parse_dt(first_seg["departure"]["at"])
                arrive_at = _parse_dt(last_seg["arrival"]["at"])
                duration_min = int((arrive_at - depart_at).total_seconds() // 60)

                airline_code = (
                    item.get("validatingAirlineCodes") or [first_seg["carrierCode"]]
                )[0]

                offers.append(Offer(
                    price=round(price, 2),
                    airline=airline_code,
                    airline_name=airline_code,  # Offers Search v2 doesn't return carrier names
                    stops=len(segments) - 1,
                    depart_at=depart_at,
                    arrive_at=arrive_at,
                    duration_min=duration_min,
                    raw_id=item["id"],
                    deep_link=None,
                ))
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed Amadeus offer: %s", exc)

        offers.sort(key=lambda o: o.price)
        return offers

    # ------------------------------------------------------------------
    # Public search with retry + backoff
    # ------------------------------------------------------------------

    def search(self, params: SearchParams) -> list[Offer]:
        last_exc: Exception = ProviderError("search failed")

        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                token = self._authenticate()
                return self._request(params, token)

            except ProviderTimeout as exc:
                last_exc = exc
                logger.warning("Amadeus timeout (attempt %d)", attempt + 1)

            except ProviderError as exc:
                last_exc = exc
                if str(exc) == "amadeus_rate_limit":
                    logger.warning("Amadeus 429, sleeping 5s (attempt %d)", attempt + 1)
                    time.sleep(5)
                elif str(exc) == "amadeus_token_expired":
                    logger.warning("Amadeus 401 — token cleared, retrying immediately")
                    # don't sleep; retry with fresh token immediately
                    continue
                else:
                    logger.warning("Amadeus error: %s (attempt %d)", exc, attempt + 1)

            if attempt < len(_RETRY_DELAYS):
                time.sleep(_RETRY_DELAYS[attempt])

        raise last_exc


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
    return dt
