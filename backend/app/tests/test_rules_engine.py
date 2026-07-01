"""
Integration tests for §6 rules-engine.
Requires running MongoDB and Redis (docker compose up mongo redis).
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import redis as sync_redis
from bson import ObjectId

from app.core.config import settings
from app.core.db import get_sync_db
from app.services.rules_engine import COOLDOWN, evaluate, evaluate_digest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    return get_sync_db()


@pytest.fixture
def r():
    client = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
    yield client
    # no global cleanup — each test cleans its own keys


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


def _make_user(db) -> dict:
    oid = ObjectId()
    db.users.insert_one({
        "_id": oid,
        "email": f"re_test_{oid}@test.com",
        "password_hash": "x",
        "plan": "free",
        "telegram_chat_id": 999000,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return db.users.find_one({"_id": oid})


def _make_watch(db, user_oid: ObjectId, rule: dict) -> dict:
    oid = ObjectId()
    db.watches.insert_one({
        "_id": oid,
        "user_id": user_oid,
        "origin": "RIX",
        "destination": "BCN",
        "date_mode": "exact",
        "depart_date": "2026-09-15",
        "rule": rule,
        "active": True,
        "lowest_seen": None,
        "lowest_seen_at": None,
        "last_checked_at": None,
        "last_alerted_at": None,
        "last_offer": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return db.watches.find_one({"_id": oid})


def _insert_snapshot(db, watch_oid: ObjectId, price, minutes_ago: int = 0):
    from datetime import timedelta
    checked_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db.price_snapshots.insert_one({
        "watch_id": watch_oid,
        "checked_at": checked_at,
        "price": price,
        "airline": "VY",
        "airline_name": "Vueling",
        "stops": 0,
        "provider": "mock",
    })


def _clear_cooldown(r, watch_id: str, rule_type: str):
    r.delete(f"cooldown:{watch_id}:{rule_type}")


# ---------------------------------------------------------------------------
# threshold rule
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_fires_when_price_at_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "threshold", "threshold_price": 100.0})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=100.0, old_lowest=None)
            assert result is True
            mock_alert.assert_called_once()
            assert r.exists(f"cooldown:{wid}:threshold")
        finally:
            _clear_cooldown(r, wid, "threshold")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_fires_when_price_below_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "threshold", "threshold_price": 100.0})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=85.0, old_lowest=None)
            assert result is True
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "threshold")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_when_price_above_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "threshold", "threshold_price": 100.0})
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=120.0, old_lowest=None)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_cooldown_suppresses_second_alert(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "threshold", "threshold_price": 100.0})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                r1 = evaluate(watch, current_price=80.0, old_lowest=None)
                r2 = evaluate(watch, current_price=79.0, old_lowest=None)
            assert r1 is True
            assert r2 is False
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "threshold")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_cooldown_ttl_matches_spec(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "threshold", "threshold_price": 100.0})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert"):
                evaluate(watch, current_price=80.0, old_lowest=None)
            ttl = r.ttl(f"cooldown:{wid}:threshold")
            assert 86390 <= ttl <= 86400  # 24h +/- 10s
        finally:
            _clear_cooldown(r, wid, "threshold")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})


# ---------------------------------------------------------------------------
# new_low rule
# ---------------------------------------------------------------------------

class TestNewLow:
    def test_fires_on_first_poll_old_lowest_none(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "new_low"})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=90.0, old_lowest=None)
            assert result is True
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "new_low")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_fires_when_new_minimum(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "new_low"})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=85.0, old_lowest=100.0)
            assert result is True
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "new_low")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_when_equal_to_old_lowest(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "new_low"})
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=100.0, old_lowest=100.0)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_when_higher_than_old_lowest(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "new_low"})
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=110.0, old_lowest=100.0)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_cooldown_ttl_is_12h(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "new_low"})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_alert"):
                evaluate(watch, current_price=90.0, old_lowest=None)
            ttl = r.ttl(f"cooldown:{wid}:new_low")
            assert 43190 <= ttl <= 43200  # 12h +/- 10s
        finally:
            _clear_cooldown(r, wid, "new_low")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})


# ---------------------------------------------------------------------------
# drop_pct rule
# ---------------------------------------------------------------------------

class TestDropPct:
    def test_fires_when_drop_exceeds_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "drop_pct", "drop_pct": 10.0})
        wid = str(watch["_id"])
        # prev = 100, current = 85 => drop = 15% >= 10%
        _insert_snapshot(db, watch["_id"], price=100.0, minutes_ago=120)
        _insert_snapshot(db, watch["_id"], price=85.0, minutes_ago=0)
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=85.0, old_lowest=100.0)
            assert result is True
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "drop_pct")
            db.price_snapshots.delete_many({"watch_id": watch["_id"]})
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_fires_when_drop_exactly_at_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "drop_pct", "drop_pct": 15.0})
        wid = str(watch["_id"])
        # prev = 100, current = 85 => drop = exactly 15%
        _insert_snapshot(db, watch["_id"], price=100.0, minutes_ago=120)
        _insert_snapshot(db, watch["_id"], price=85.0, minutes_ago=0)
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=85.0, old_lowest=None)
            assert result is True
            mock_alert.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "drop_pct")
            db.price_snapshots.delete_many({"watch_id": watch["_id"]})
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_when_drop_below_threshold(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "drop_pct", "drop_pct": 20.0})
        # prev = 100, current = 90 => drop = 10% < 20%
        _insert_snapshot(db, watch["_id"], price=100.0, minutes_ago=120)
        _insert_snapshot(db, watch["_id"], price=90.0, minutes_ago=0)
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=90.0, old_lowest=None)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.price_snapshots.delete_many({"watch_id": watch["_id"]})
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_with_only_one_snapshot(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "drop_pct", "drop_pct": 10.0})
        # Only current snapshot — no previous to compare
        _insert_snapshot(db, watch["_id"], price=90.0, minutes_ago=0)
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=90.0, old_lowest=None)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.price_snapshots.delete_many({"watch_id": watch["_id"]})
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_does_not_fire_when_prev_snapshot_is_null_price(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "drop_pct", "drop_pct": 10.0})
        # Previous snapshot has null price (no offers found that run)
        _insert_snapshot(db, watch["_id"], price=None, minutes_ago=120)
        _insert_snapshot(db, watch["_id"], price=85.0, minutes_ago=0)
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=85.0, old_lowest=None)
            # prev with price=null is filtered out by $ne:None; no valid prev => False
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.price_snapshots.delete_many({"watch_id": watch["_id"]})
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})


# ---------------------------------------------------------------------------
# digest rule
# ---------------------------------------------------------------------------

class TestDigestRule:
    def test_evaluate_always_returns_false_for_digest(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "digest", "digest_time": "08:00"})
        try:
            with patch("app.services.notifier.send_alert") as mock_alert:
                result = evaluate(watch, current_price=90.0, old_lowest=None)
            assert result is False
            mock_alert.assert_not_called()
        finally:
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})


# ---------------------------------------------------------------------------
# evaluate_digest
# ---------------------------------------------------------------------------

class TestEvaluateDigest:
    def test_calls_send_digest_and_sets_cooldown(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "digest", "digest_time": "08:00"})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_digest") as mock_digest:
                evaluate_digest(watch)
            mock_digest.assert_called_once()
            assert r.exists(f"cooldown:{wid}:digest")
            ttl = r.ttl(f"cooldown:{wid}:digest")
            assert 71990 <= ttl <= 72000  # 20h +/- 10s
        finally:
            _clear_cooldown(r, wid, "digest")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_cooldown_suppresses_second_digest(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "digest", "digest_time": "08:00"})
        wid = str(watch["_id"])
        try:
            with patch("app.services.notifier.send_digest") as mock_digest:
                evaluate_digest(watch)
                evaluate_digest(watch)
            mock_digest.assert_called_once()
        finally:
            _clear_cooldown(r, wid, "digest")
            db.watches.delete_one({"_id": watch["_id"]})
            db.users.delete_one({"_id": user["_id"]})

    def test_skips_when_user_not_found(self, db, r):
        user = _make_user(db)
        watch = _make_watch(db, user["_id"], {"type": "digest", "digest_time": "08:00"})
        wid = str(watch["_id"])
        db.users.delete_one({"_id": user["_id"]})
        try:
            with patch("app.services.notifier.send_digest") as mock_digest:
                evaluate_digest(watch)
            mock_digest.assert_not_called()
        finally:
            _clear_cooldown(r, wid, "digest")
            db.watches.delete_one({"_id": watch["_id"]})
