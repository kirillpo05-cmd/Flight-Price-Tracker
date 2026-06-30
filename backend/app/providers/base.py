from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class SearchParams:
    origin: str
    destination: str
    depart_date: date
    passengers: int
    cabin: str
    return_date: date | None = None
    date_to: date | None = None  # populated for date_mode="range"; mock uses it for random date selection
    currency: str = "EUR"


@dataclass
class Offer:
    price: float
    airline: str
    airline_name: str
    stops: int
    depart_at: datetime
    arrive_at: datetime
    duration_min: int
    raw_id: str
    deep_link: str | None = None


class ProviderTimeout(Exception):
    pass


class ProviderError(Exception):
    pass


class NoOffersFound(Exception):
    pass


class FareProvider(ABC):
    @abstractmethod
    def search(self, params: SearchParams) -> list[Offer]:
        """Return offers sorted by price asc. Raises ProviderTimeout | ProviderError."""
        raise NotImplementedError
