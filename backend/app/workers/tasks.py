import logging
from datetime import datetime, timedelta, timezone

import redis as sync_redis

from app.core.config import settings
from app.core.db import get_sync_db
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
# poll_watch — stub registered so the worker doesn't crash on §2/§4 queue msgs.
# Full implementation is in §5 (poll-worker).
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.tasks.poll_watch",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def poll_watch(self, watch_id: str) -> None:
    # §5 implementation goes here.
    logger.warning("poll_watch(%s): not yet implemented — see §5", watch_id)


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
