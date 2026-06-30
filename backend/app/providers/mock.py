import hashlib
import random
from datetime import date, datetime, timedelta, timezone

from app.providers.base import FareProvider, Offer, SearchParams

_AIRLINES = [
    ("W6", "Wizz Air"),
    ("VY", "Vueling"),
    ("FR", "Ryanair"),
]


class MockProvider(FareProvider):
    """Deterministic fake provider — no API keys needed (FARE_PROVIDER=mock).

    Base price: hash(origin+destination) % 100 + 60 EUR per route.
    Noise seed: route_key + depart_date.isoformat() → reproducible ±15%.
    For range mode (date_to set): depart date is picked randomly each call,
    so price varies between calls as the spec requires.
    """

    def search(self, params: SearchParams) -> list[Offer]:
        route_key = params.origin + params.destination

        # Deterministic base price per route (60–159 EUR)
        route_hash = int(hashlib.md5(route_key.encode()).hexdigest(), 16)
        base_price = route_hash % 100 + 60

        # Range mode: pick a random (unseeded) departure date so price varies per call
        if params.date_to is not None and params.date_to > params.depart_date:
            days_span = (params.date_to - params.depart_date).days
            offset = random.randint(0, days_span)
            depart_date = params.depart_date + timedelta(days=offset)
        else:
            depart_date = params.depart_date

        # Seeded RNG for reproducible noise given route + date
        rng = random.Random(route_key + depart_date.isoformat())

        n_offers = rng.randint(3, min(5, len(_AIRLINES)))
        airlines = rng.sample(_AIRLINES, n_offers)
        offers: list[Offer] = []

        for i, (code, name) in enumerate(airlines):
            noise = 1.0 + rng.uniform(-0.15, 0.15)
            # Each subsequent offer is slightly more expensive
            price = round(base_price * noise * (1.0 + i * 0.06), 2)

            stops = rng.choices([0, 1], weights=[2, 1])[0]
            depart_hour = rng.randint(6, 20)
            flight_duration = 90 + rng.randint(0, 180) + stops * 90

            depart_at = datetime(
                depart_date.year, depart_date.month, depart_date.day,
                depart_hour, 0, 0, tzinfo=timezone.utc,
            )
            arrive_at = depart_at + timedelta(minutes=flight_duration)

            offers.append(Offer(
                price=price,
                airline=code,
                airline_name=name,
                stops=stops,
                depart_at=depart_at,
                arrive_at=arrive_at,
                duration_min=flight_duration,
                raw_id=f"mock-{route_key}-{depart_date.isoformat()}-{code}",
                deep_link=None,
            ))

        offers.sort(key=lambda o: o.price)
        return offers
