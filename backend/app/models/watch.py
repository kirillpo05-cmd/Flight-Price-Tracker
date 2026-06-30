import re
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RuleIn(BaseModel):
    type: Literal["threshold", "new_low", "drop_pct", "digest"]
    threshold_price: float | None = None
    drop_pct: float | None = None
    digest_time: str | None = None

    @model_validator(mode="after")
    def validate_rule_fields(self) -> "RuleIn":
        if self.type == "threshold":
            if self.threshold_price is None or self.threshold_price <= 0:
                raise ValueError("threshold_price must be > 0")
        elif self.type == "drop_pct":
            if self.drop_pct is None or not (1.0 <= self.drop_pct <= 99.0):
                raise ValueError("drop_pct must be between 1 and 99")
        elif self.type == "digest":
            # Scheduler fires hourly at :00, so only HH:00 values will ever match.
            if not self.digest_time or not re.match(r"^\d{2}:00$", self.digest_time):
                raise ValueError("digest_time must be in HH:00 format (e.g. '08:00')")
        return self


class CreateWatchRequest(BaseModel):
    origin: str
    destination: str
    date_mode: Literal["exact", "range"]
    depart_date: date | None = None
    return_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    cabin: Literal["economy", "business", "first"] = "economy"
    rule: RuleIn

    @field_validator("origin", "destination")
    @classmethod
    def validate_iata(cls, v: str) -> str:
        if not re.match(r"^[A-Z]{3}$", v):
            raise ValueError("Must be 3 uppercase letters (IATA code)")
        return v

    @model_validator(mode="after")
    def validate_watch(self) -> "CreateWatchRequest":
        if self.origin == self.destination:
            raise ValueError("origin and destination must be different")

        tomorrow = date.today() + timedelta(days=1)

        if self.date_mode == "exact":
            if self.depart_date is None:
                raise ValueError("depart_date is required for exact mode")
            if self.depart_date < tomorrow:
                raise ValueError("depart_date must be in the future")
            if self.return_date is not None and self.return_date <= self.depart_date:
                raise ValueError("return_date must be after depart_date")
        else:
            if self.date_from is None or self.date_to is None:
                raise ValueError("date_from and date_to are required for range mode")
            if self.date_from < tomorrow:
                raise ValueError("date_from must be in the future")
            if self.date_from >= self.date_to:
                raise ValueError("date_from must be before date_to")
            if (self.date_to - self.date_from).days > 90:
                raise ValueError("Date range must not exceed 90 days")

        return self


class PatchWatchRequest(BaseModel):
    active: bool | None = None
    rule: RuleIn | None = None
    origin: str | None = None       # immutable — rejected in handler
    destination: str | None = None  # immutable — rejected in handler


class WatchResponse(BaseModel):
    watch_id: str
    user_id: str
    origin: str
    destination: str
    date_mode: str
    depart_date: date | None
    return_date: date | None
    date_from: date | None
    date_to: date | None
    passengers: int
    cabin: str
    rule: dict
    active: bool
    lowest_seen: float | None
    lowest_seen_at: datetime | None
    last_checked_at: datetime | None
    last_alerted_at: datetime | None
    last_offer: dict | None
    created_at: datetime
    updated_at: datetime


class SnapshotResponse(BaseModel):
    checked_at: datetime
    price: float | None
    airline: str | None
    airline_name: str | None
    stops: int | None
