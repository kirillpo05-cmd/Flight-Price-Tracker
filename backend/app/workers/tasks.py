import logging
from datetime import date, datetime, timedelta, timezone

import redis as sync_redis
from bson import ObjectId
from bson.errors import InvalidId

from app.core.config import settings
from app.core.db import get_sync_db
from app.providers.base import ProviderError, ProviderTimeout
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

POLL_INTERVALS: dict[str, timedelta] = {
    "free": timedelta(hours=12),
    "pro": timedelta(hours=3),
    "team": timedelta(hours=1),
}

_SCHEDULER_LOCK_KEY = "scheduler:lock"
_SCHEDULER_LOCK_TTL = 300  # seconds — SPEC §4.2
_SCHEDULER_LAST_RUN_KEY = "scheduler:last_run"
_STAGGER_WINDOW = 1800  # spread tasks over 30 min — SPEC §4.5


def _redis() -> sync_redis.Redis:
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def _to_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC-aware (pymongo returns naive UTC datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# poll_watch — SPEC §5.5
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.tasks.poll_watch",
    bind=True,
    max_retries=3,
    autoretry_for=(ProviderTimeout, ProviderError),
    retry_backoff=True,
    retry_backoff_max=120,
    default_retry_delay=60,
)
def poll_watch(self, watch_id: str) -> None:  # noqa: C901
    from app.providers import get_provider
    from app.providers.base import SearchParams
    from app.services.price_service import (
        cache_last_price,
        mark_checked,
        update_watch_after_poll,
        write_snapshot,
    )
    from app.services.rules_engine import evaluate

    # ── Step 1: load watch ──────────────────────────────────────────────────
    try:
        watch_oid = ObjectId(watch_id)
    except InvalidId:
        logger.error("poll_watch: invalid ObjectId '%s', dropping task", watch_id)
        return

    db = get_sync_db()
    watch = db.watches.find_one({"_id": watch_oid})

    if watch is None:
        logger.info("poll_watch: watch %s not found (deleted?), skipping", watch_id)
        return
    if not watch.get("active", False):
        logger.info("poll_watch: watch %s is inactive, skipping", watch_id)
        return

    # ── Step 2: load user ───────────────────────────────────────────────────
    user = db.users.find_one({"_id": watch["user_id"]})
    if user is None:
        logger.warning("poll_watch: user for watch %s not found, skipping", watch_id)
        return

    plan = user.get("plan", "free")

    # ── Step 3 & 4: provider + SearchParams ────────────────────────────────
    provider = get_provider()
    now = datetime.now(timezone.utc)

    if watch["date_mode"] == "exact":
        raw_depart = watch.get("depart_date")
        raw_return = watch.get("return_date")
        depart_date = date.fromisoformat(raw_depart) if raw_depart else None
        return_date = date.fromisoformat(raw_return) if raw_return else None
        date_to = None
    else:  # range
        raw_from = watch.get("date_from")
        raw_to = watch.get("date_to")
        depart_date = date.fromisoformat(raw_from) if raw_from else None
        return_date = None
        date_to = date.fromisoformat(raw_to) if raw_to else None

    if depart_date is None:
        logger.error("poll_watch: watch %s missing departure date, skipping", watch_id)
        return

    params = SearchParams(
        origin=watch["origin"],
        destination=watch["destination"],
        depart_date=depart_date,
        return_date=return_date,
        date_to=date_to,
        passengers=watch.get("passengers", 1),
        cabin=watch.get("cabin", "economy"),
    )

    # ── Step 5: search (autoretry handles ProviderTimeout / ProviderError) ──
    provider_name = settings.FARE_PROVIDER
    offers = provider.search(params)

    # ── Step 6: no offers ───────────────────────────────────────────────────
    if not offers:
        write_snapshot(db, watch_oid, now, offer=None, provider_name=provider_name)
        mark_checked(db, watch_oid, now)
        logger.info("poll_watch: no offers found for watch %s", watch_id)
        return

    # ── Step 7: best offer ──────────────────────────────────────────────────
    best = offers[0]

    # ── Step 8: write snapshot ──────────────────────────────────────────────
    write_snapshot(db, watch_oid, now, offer=best, provider_name=provider_name)

    # ── Step 9: atomic watch update ($min lowest_seen) ──────────────────────
    old_lowest = update_watch_after_poll(db, watch_oid, best, now)

    # ── Step 10: Redis cache ────────────────────────────────────────────────
    r = _redis()
    cache_last_price(r, watch_id, best, now, plan)

    # ── Step 11: rules engine ───────────────────────────────────────────────
    evaluate(watch, current_price=best.price, old_lowest=old_lowest)

    logger.info(
        "poll_watch: watch=%s price=%.2f airline=%s old_lowest=%s",
        watch_id, best.price, best.airline,
        f"{old_lowest:.2f}" if old_lowest is not None else "None",
    )


# ---------------------------------------------------------------------------
# fan_out_polls — SPEC §4.5
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.fan_out_polls")
def fan_out_polls() -> None:
    r = _redis()

    # Idempotency lock — only one Beat instance fans out at a time
    acquired = r.set(_SCHEDULER_LOCK_KEY, "1", ex=_SCHEDULER_LOCK_TTL, nx=True)
    if not acquired:
        logger.info("fan_out_polls: lock held by another instance, skipping")
        return

    try:
        db = get_sync_db()
        now = datetime.now(timezone.utc)

        watches = list(db.watches.find({"active": True}))
        if not watches:
            logger.info("fan_out_polls: no active watches")
            r.set(_SCHEDULER_LAST_RUN_KEY, now.isoformat())
            return

        # Build user plan cache to avoid N+1 queries
        user_ids = list({w["user_id"] for w in watches})
        users = {u["_id"]: u for u in db.users.find({"_id": {"$in": user_ids}})}

        due_watches = []
        for watch in watches:
            user = users.get(watch["user_id"])
            if user is None:
                logger.warning("fan_out_polls: user not found for watch %s, skipping", watch["_id"])
                continue

            plan = user.get("plan", "free")
            interval = POLL_INTERVALS.get(plan, POLL_INTERVALS["free"])

            anchor = watch.get("last_checked_at") or watch.get("created_at")
            if anchor is None:
                due_watches.append(watch)
                continue

            anchor = _to_utc(anchor)
            if now >= anchor + interval:
                due_watches.append(watch)

        if not due_watches:
            logger.info("fan_out_polls: no watches due, next check at next hour")
            r.set(_SCHEDULER_LAST_RUN_KEY, now.isoformat())
            return

        n = len(due_watches)
        logger.info("fan_out_polls: dispatching %d poll tasks", n)

        for i, watch in enumerate(due_watches):
            # Stagger evenly across _STAGGER_WINDOW seconds — SPEC §4.5
            countdown = i * (_STAGGER_WINDOW / n)
            poll_watch.apply_async(
                args=[str(watch["_id"])],
                countdown=countdown,
            )

        r.set(_SCHEDULER_LAST_RUN_KEY, now.isoformat())
        logger.info("fan_out_polls: done, %d tasks queued", n)

    except Exception:
        logger.exception("fan_out_polls: unexpected error")
        raise
    # Lock expires by TTL — no explicit delete needed (SPEC §4.5 step 7)


# ---------------------------------------------------------------------------
# send_digests — SPEC §4.5
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.send_digests")
def send_digests() -> None:
    db = get_sync_db()
    now = datetime.now(timezone.utc)

    # Match digest_time rounded to current hour: "HH:00"
    current_hour = now.strftime("%H:00")

    watches = list(db.watches.find({
        "active": True,
        "rule.type": "digest",
        "rule.digest_time": current_hour,
    }))

    if not watches:
        logger.info("send_digests: no digest watches scheduled for %s UTC", current_hour)
        return

    logger.info("send_digests: sending digest for %d watch(es) at %s UTC", len(watches), current_hour)

    # Lazy import — rules_engine will be implemented in §6
    try:
        from app.services.rules_engine import evaluate_digest
    except ImportError:
        logger.error("send_digests: rules_engine.evaluate_digest not available yet (§6)")
        return

    for watch in watches:
        try:
            evaluate_digest(watch)
        except Exception:
            logger.exception("send_digests: failed for watch %s", watch["_id"])
