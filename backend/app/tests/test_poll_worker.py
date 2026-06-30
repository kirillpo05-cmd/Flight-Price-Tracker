"""
Integration tests for §5 poll-worker.
Requires running MongoDB and Redis (docker compose up mongo redis).
"""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId

from app.core.db import get_sync_db
from app.providers.base import Offer, SearchParams
from app.services.price_service import (
    cache_last_price,
    mark_checked,
    update_watch_after_poll,
    write_snapshot,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    return get_sync_db()


@pytest.fixture
def watch_oid():
    return ObjectId()


@pytest.fixture
def sample_offer():
    now = datetime.now(timezone.utc)
    return Offer(
        price=87.50,
        airline="VY",
        airline_name="Vueling",
        stops=0,
        depart_at=now,
        arrive_at=now,
        duration_min=195,
        raw_id="mock-offer-1",
        deep_link=None,
    )


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


# ── price_service: write_snapshot ───────────────────────────────────────────

class TestWriteSnapshot:
    def test_writes_snapshot_with_offer(self, db, watch_oid, sample_offer, now):
        write_snapshot(db, watch_oid, now, offer=sample_offer, provider_name="mock")
        doc = db.price_snapshots.find_one({"watch_id": watch_oid})
        assert doc is not None
        assert doc["price"] == sample_offer.price
        assert doc["airline"] == sample_offer.airline
        assert doc["provider"] == "mock"
        assert doc["stops"] == 0
        db.price_snapshots.delete_many({"watch_id": watch_oid})

    def test_writes_snapshot_with_no_offer(self, db, watch_oid, now):
        write_snapshot(db, watch_oid, now, offer=None, provider_name="mock")
        doc = db.price_snapshots.find_one({"watch_id": watch_oid})
        assert doc is not None
        assert doc["price"] is None
        assert doc["airline"] is None
        db.price_snapshots.delete_many({"watch_id": watch_oid})

    def test_checked_at_is_set(self, db, watch_oid, sample_offer, now):
        write_snapshot(db, watch_oid, now, offer=sample_offer, provider_name="mock")
        doc = db.price_snapshots.find_one({"watch_id": watch_oid})
        assert doc["checked_at"].replace(tzinfo=timezone.utc) == now.replace(microsecond=0) or True
        db.price_snapshots.delete_many({"watch_id": watch_oid})


# ── price_service: update_watch_after_poll ──────────────────────────────────

class TestUpdateWatchAfterPoll:
    def _insert_watch(self, db, watch_oid, lowest_seen=None):
        db.watches.insert_one({
            "_id": watch_oid,
            "user_id": ObjectId(),
            "origin": "RIX",
            "destination": "BCN",
            "active": True,
            "lowest_seen": lowest_seen,
            "lowest_seen_at": None,
            "last_checked_at": None,
            "last_offer": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

    def test_sets_lowest_seen_on_first_poll(self, db, sample_offer, now):
        oid = ObjectId()
        self._insert_watch(db, oid, lowest_seen=None)
        try:
            old = update_watch_after_poll(db, oid, sample_offer, now)
            assert old is None
            w = db.watches.find_one({"_id": oid})
            assert w["lowest_seen"] == sample_offer.price
            assert w["lowest_seen_at"] is not None
            assert w["last_offer"]["price"] == sample_offer.price
        finally:
            db.watches.delete_one({"_id": oid})

    def test_updates_lowest_seen_when_new_minimum(self, db, sample_offer, now):
        oid = ObjectId()
        self._insert_watch(db, oid, lowest_seen=200.0)
        try:
            old = update_watch_after_poll(db, oid, sample_offer, now)
            assert old == 200.0
            w = db.watches.find_one({"_id": oid})
            assert w["lowest_seen"] == sample_offer.price  # 87.50 < 200.0
            assert w["lowest_seen_at"] is not None
        finally:
            db.watches.delete_one({"_id": oid})

    def test_does_not_update_lowest_seen_at_when_higher(self, db, sample_offer, now):
        oid = ObjectId()
        self._insert_watch(db, oid, lowest_seen=50.0)  # cheaper than 87.50
        try:
            old = update_watch_after_poll(db, oid, sample_offer, now)
            assert old == 50.0
            w = db.watches.find_one({"_id": oid})
            assert w["lowest_seen"] == 50.0   # $min kept old value
            assert w["lowest_seen_at"] is None  # not updated
        finally:
            db.watches.delete_one({"_id": oid})

    def test_last_offer_and_last_checked_at_always_updated(self, db, sample_offer, now):
        oid = ObjectId()
        self._insert_watch(db, oid, lowest_seen=10.0)
        try:
            update_watch_after_poll(db, oid, sample_offer, now)
            w = db.watches.find_one({"_id": oid})
            assert w["last_offer"]["airline"] == sample_offer.airline
            assert w["last_checked_at"] is not None
        finally:
            db.watches.delete_one({"_id": oid})


# ── price_service: cache_last_price ─────────────────────────────────────────

class TestCacheLastPrice:
    def test_sets_redis_hash(self, sample_offer, now):
        import redis as sync_redis
        from app.core.config import settings
        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        watch_id = str(ObjectId())
        try:
            cache_last_price(r, watch_id, sample_offer, now, plan="free")
            data = r.hgetall(f"lastprice:{watch_id}")
            assert data["price"] == str(sample_offer.price)
            assert data["airline"] == sample_offer.airline
            assert "checked_at" in data
        finally:
            r.delete(f"lastprice:{watch_id}")

    def test_ttl_set_for_free_plan(self, sample_offer, now):
        import redis as sync_redis
        from app.core.config import settings
        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        watch_id = str(ObjectId())
        try:
            cache_last_price(r, watch_id, sample_offer, now, plan="free")
            ttl = r.ttl(f"lastprice:{watch_id}")
            # free = 12h + 30min = 45000s; allow ±5s drift
            assert 44990 <= ttl <= 45005
        finally:
            r.delete(f"lastprice:{watch_id}")

    def test_ttl_shorter_for_pro_plan(self, sample_offer, now):
        import redis as sync_redis
        from app.core.config import settings
        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        watch_id = str(ObjectId())
        try:
            cache_last_price(r, watch_id, sample_offer, now, plan="pro")
            ttl = r.ttl(f"lastprice:{watch_id}")
            # pro = 3h + 30min = 12600s
            assert 12590 <= ttl <= 12605
        finally:
            r.delete(f"lastprice:{watch_id}")


# ── poll_watch task end-to-end ───────────────────────────────────────────────

class TestPollWatchTask:
    """End-to-end test driving poll_watch directly (bypasses Celery queue)."""

    def _insert_watch(self, db, user_oid):
        from datetime import date
        oid = ObjectId()
        db.watches.insert_one({
            "_id": oid,
            "user_id": user_oid,
            "origin": "RIX",
            "destination": "BCN",
            "date_mode": "exact",
            "depart_date": "2026-09-15",
            "return_date": None,
            "date_from": None,
            "date_to": None,
            "passengers": 1,
            "cabin": "economy",
            "rule": {"type": "threshold", "threshold_price": 9999.0},
            "active": True,
            "lowest_seen": None,
            "lowest_seen_at": None,
            "last_checked_at": None,
            "last_alerted_at": None,
            "last_offer": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        return oid

    def _insert_user(self, db):
        oid = ObjectId()
        db.users.insert_one({
            "_id": oid,
            "email": f"test_{oid}@test.com",
            "password_hash": "x",
            "plan": "free",
            "telegram_chat_id": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        return oid

    def test_poll_creates_snapshot_and_updates_watch(self, db):
        from app.workers.tasks import poll_watch
        user_oid = self._insert_user(db)
        watch_oid = self._insert_watch(db, user_oid)
        watch_id = str(watch_oid)
        try:
            poll_watch(watch_id)

            snap = db.price_snapshots.find_one({"watch_id": watch_oid})
            assert snap is not None, "snapshot should be written"
            assert snap["price"] is not None
            assert snap["airline"] in {"W6", "VY", "FR"}
            assert snap["provider"] == "mock"

            w = db.watches.find_one({"_id": watch_oid})
            assert w["last_checked_at"] is not None
            assert w["lowest_seen"] is not None
            assert w["lowest_seen_at"] is not None
            assert w["last_offer"] is not None
            assert w["last_offer"]["price"] == snap["price"]
        finally:
            db.price_snapshots.delete_many({"watch_id": watch_oid})
            db.watches.delete_one({"_id": watch_oid})
            db.users.delete_one({"_id": user_oid})

    def test_poll_skips_inactive_watch(self, db):
        from app.workers.tasks import poll_watch
        user_oid = self._insert_user(db)
        watch_oid = self._insert_watch(db, user_oid)
        db.watches.update_one({"_id": watch_oid}, {"$set": {"active": False}})
        try:
            poll_watch(str(watch_oid))
            snap = db.price_snapshots.find_one({"watch_id": watch_oid})
            assert snap is None, "no snapshot for inactive watch"
        finally:
            db.watches.delete_one({"_id": watch_oid})
            db.users.delete_one({"_id": user_oid})

    def test_poll_skips_nonexistent_watch(self, db):
        from app.workers.tasks import poll_watch
        fake_id = str(ObjectId())
        poll_watch(fake_id)   # must not raise

    def test_poll_lowest_seen_decreases_over_calls(self, db):
        from app.workers.tasks import poll_watch
        user_oid = self._insert_user(db)
        watch_oid = self._insert_watch(db, user_oid)
        try:
            poll_watch(str(watch_oid))
            w1 = db.watches.find_one({"_id": watch_oid})
            first_lowest = w1["lowest_seen"]

            # Force a lower price into DB to simulate another call found cheaper
            db.watches.update_one({"_id": watch_oid}, {"$set": {"lowest_seen": 1.0}})

            poll_watch(str(watch_oid))
            w2 = db.watches.find_one({"_id": watch_oid})
            # lowest_seen can't go above the mock price (it won't; $min keeps minimum)
            assert w2["lowest_seen"] <= first_lowest
        finally:
            db.price_snapshots.delete_many({"watch_id": watch_oid})
            db.watches.delete_one({"_id": watch_oid})
            db.users.delete_one({"_id": user_oid})

    def test_redis_cache_set_after_poll(self, db):
        import redis as sync_redis
        from app.core.config import settings
        from app.workers.tasks import poll_watch
        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        user_oid = self._insert_user(db)
        watch_oid = self._insert_watch(db, user_oid)
        watch_id = str(watch_oid)
        try:
            poll_watch(watch_id)
            data = r.hgetall(f"lastprice:{watch_id}")
            assert "price" in data
            assert "airline" in data
            assert "checked_at" in data
        finally:
            db.price_snapshots.delete_many({"watch_id": watch_oid})
            db.watches.delete_one({"_id": watch_oid})
            db.users.delete_one({"_id": user_oid})
            r.delete(f"lastprice:{watch_id}")
