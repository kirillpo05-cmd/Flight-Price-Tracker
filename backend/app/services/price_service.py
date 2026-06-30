"""
Snapshot persistence and watch state update for poll_watch — SPEC.md §5.5.
Kept separate from tasks.py so logic is testable without Celery.
"""
import logging
from datetime import datetime

import redis as sync_redis
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.providers.base import Offer

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS: dict[str, int] = {
    "free": 12 * 3600,
    "pro": 3 * 3600,
    "team": 1 * 3600,
}


def write_snapshot(
    db: Database,
    watch_oid: ObjectId,
    now: datetime,
    offer: Offer | None,
    provider_name: str,
) -> None:
    """Insert one document into the price_snapshots time-series collection."""
    doc: dict = {
        "watch_id": watch_oid,   # metaField
        "checked_at": now,        # timeField
        "provider": provider_name,
        "price": offer.price if offer else None,
        "airline": offer.airline if offer else None,
        "airline_name": offer.airline_name if offer else None,
        "stops": offer.stops if offer else None,
        "depart_at": offer.depart_at if offer else None,
        "arrive_at": offer.arrive_at if offer else None,
        "duration_min": offer.duration_min if offer else None,
        "deep_link": offer.deep_link if offer else None,
    }
    db.price_snapshots.insert_one(doc)


def update_watch_after_poll(
    db: Database,
    watch_oid: ObjectId,
    best: Offer,
    now: datetime,
) -> float | None:
    """
    Atomically update watches after a successful poll.
    Uses $min for lowest_seen so concurrent tasks don't race.
    Returns old_lowest (before this update) so rules_engine can compare.
    """
    last_offer_doc = {
        "price": best.price,
        "airline": best.airline,
        "airline_name": best.airline_name,
        "stops": best.stops,
        "depart_at": best.depart_at,
        "arrive_at": best.arrive_at,
        "duration_min": best.duration_min,
        "deep_link": best.deep_link,
    }

    # Aggregation pipeline update so $ifNull handles the null→first-write case.
    # MongoDB's plain $min treats null as less than any number, so $min(null, 87.5)
    # would keep null — wrong on the first poll.
    old_doc = db.watches.find_one_and_update(
        {"_id": watch_oid},
        [
            {
                "$set": {
                    "lowest_seen": {
                        "$min": [best.price, {"$ifNull": ["$lowest_seen", best.price]}]
                    },
                    "last_checked_at": now,
                    "last_offer": last_offer_doc,
                    "updated_at": now,
                }
            }
        ],
        return_document=ReturnDocument.BEFORE,
    )

    old_lowest: float | None = old_doc.get("lowest_seen") if old_doc else None

    # Update lowest_seen_at only when a new minimum was actually set — SPEC §5.6
    if old_lowest is None or best.price < old_lowest:
        db.watches.update_one(
            {"_id": watch_oid},
            {"$set": {"lowest_seen_at": now}},
        )

    return old_lowest


def mark_checked(db: Database, watch_oid: ObjectId, now: datetime) -> None:
    """Update last_checked_at when provider returned no offers."""
    db.watches.update_one(
        {"_id": watch_oid},
        {"$set": {"last_checked_at": now, "updated_at": now}},
    )


def cache_last_price(
    r: sync_redis.Redis,
    watch_id: str,
    best: Offer,
    now: datetime,
    plan: str,
) -> None:
    """Write lastprice:{watch_id} hash to Redis with TTL = poll_interval + 30 min."""
    poll_seconds = _POLL_INTERVAL_SECONDS.get(plan, _POLL_INTERVAL_SECONDS["free"])
    ttl = poll_seconds + 30 * 60

    r.hset(
        f"lastprice:{watch_id}",
        mapping={
            "price": str(best.price),
            "airline": best.airline,
            "checked_at": now.isoformat(),
        },
    )
    r.expire(f"lastprice:{watch_id}", ttl)
