"""
Rules engine — SPEC.md §6.
Evaluates watch rules after each poll and fires alerts via notifier.
Called synchronously from Celery workers (sync context).
"""
import logging

import redis as sync_redis

from app.core.config import settings
from app.core.db import get_sync_db

logger = logging.getLogger(__name__)

# Cooldown TTLs in seconds — SPEC §6.5
COOLDOWN: dict[str, int] = {
    "threshold": 86400,  # 24 h
    "new_low":   43200,  # 12 h
    "drop_pct":  43200,  # 12 h
    "digest":    72000,  # 20 h
}


def _redis() -> sync_redis.Redis:
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def evaluate(watch: dict, current_price: float, old_lowest: float | None) -> bool:
    """
    Evaluate rule for watch after a poll.
    Returns True if an alert was sent, False otherwise.
    Handles cooldown suppression atomically via Redis SET NX.
    """
    rule = watch.get("rule", {})
    rule_type = rule.get("type")
    watch_id = str(watch["_id"])

    fired = False

    if rule_type == "threshold":
        fired = current_price <= rule["threshold_price"]

    elif rule_type == "new_low":
        # old_lowest is the value BEFORE this poll's $min update — SPEC §6.5
        fired = old_lowest is None or current_price < old_lowest

    elif rule_type == "drop_pct":
        fired = _eval_drop_pct(watch, current_price, rule)

    elif rule_type == "digest":
        fired = False  # managed by send_digests Beat task

    if not fired:
        return False

    # SET NX is atomic — only one concurrent evaluate wins the cooldown race
    r = _redis()
    cooldown_key = f"cooldown:{watch_id}:{rule_type}"
    acquired = r.set(cooldown_key, "1", ex=COOLDOWN.get(rule_type, 86400), nx=True)
    if not acquired:
        logger.info(
            "evaluate: cooldown active watch=%s rule=%s, suppressing alert",
            watch_id, rule_type,
        )
        return False

    db = get_sync_db()
    user = db.users.find_one({"_id": watch["user_id"]})
    if user is None:
        logger.warning("evaluate: user not found for watch=%s, cannot send alert", watch_id)
        return False

    from app.services.notifier import send_alert
    send_alert(watch=watch, user=user, price=current_price, rule_type=rule_type)

    logger.info(
        "evaluate: alert fired watch=%s rule=%s price=%.2f",
        watch_id, rule_type, current_price,
    )
    return True


def _eval_drop_pct(watch: dict, current_price: float, rule: dict) -> bool:
    """
    Returns True if price dropped >= rule.drop_pct% compared to the previous
    non-null snapshot (skip=1 to skip the snapshot just written by poll_watch).
    """
    db = get_sync_db()

    # skip=1 skips the just-written current snapshot — SPEC §6.5
    cursor = db.price_snapshots.find(
        {"watch_id": watch["_id"], "price": {"$ne": None}},
        sort=[("checked_at", -1)],
    ).skip(1).limit(1)

    prev = next(cursor, None)
    if prev is None or prev.get("price") is None:
        return False

    drop_pct = (prev["price"] - current_price) / prev["price"] * 100
    return drop_pct >= rule.get("drop_pct", 0)


def evaluate_digest(watch: dict) -> None:
    """
    Called by send_digests Beat task.
    Sends digest if not in cooldown; sets 20-h cooldown atomically.
    """
    watch_id = str(watch["_id"])
    r = _redis()

    cooldown_key = f"cooldown:{watch_id}:digest"
    acquired = r.set(cooldown_key, "1", ex=COOLDOWN["digest"], nx=True)
    if not acquired:
        logger.info("evaluate_digest: cooldown active for watch=%s, skipping", watch_id)
        return

    db = get_sync_db()
    user = db.users.find_one({"_id": watch["user_id"]})
    if user is None:
        logger.warning("evaluate_digest: user not found for watch=%s, skipping", watch_id)
        return

    from app.services.notifier import send_digest
    send_digest(watch=watch, user=user)
