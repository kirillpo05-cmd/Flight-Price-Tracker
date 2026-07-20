"""
Tests for §7 notifier service and alerts API.
Requires MongoDB + Redis (docker compose up mongo redis).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from bson import ObjectId
from httpx import ASGITransport, AsyncClient

from app.core.db import get_sync_db
from app.core.security import create_access_token
from app.main import app
from app.services.notifier import (
    _build_telegram_alert,
    _build_telegram_digest,
    send_alert,
    send_digest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, plan: str = "free", telegram_chat_id: int | None = 123456) -> dict:
    oid = ObjectId()
    db.users.insert_one({
        "_id": oid,
        "email": f"notifier_{oid}@test.com",
        "password_hash": "x",
        "plan": plan,
        "telegram_chat_id": telegram_chat_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return db.users.find_one({"_id": oid})


def _make_watch(db, user_oid: ObjectId, rule: dict | None = None) -> dict:
    oid = ObjectId()
    now = datetime.now(timezone.utc)
    db.watches.insert_one({
        "_id": oid,
        "user_id": user_oid,
        "origin": "RIX",
        "destination": "BCN",
        "date_mode": "exact",
        "depart_date": "2026-09-15",
        "rule": rule or {"type": "threshold", "threshold_price": 100.0},
        "active": True,
        "lowest_seen": 80.0,
        "lowest_seen_at": now,
        "last_checked_at": now,
        "last_alerted_at": None,
        "last_offer": {
            "price": 85.0,
            "airline": "VY",
            "airline_name": "Vueling",
            "stops": 0,
            "depart_at": now,
            "arrive_at": now,
            "duration_min": 195,
            "deep_link": "https://example.com/book",
        },
        "created_at": now,
        "updated_at": now,
    })
    return db.watches.find_one({"_id": oid})


def _cleanup(db, user_oid, watch_oid):
    db.alerts.delete_many({"watch_id": watch_oid})
    db.watches.delete_one({"_id": watch_oid})
    db.users.delete_one({"_id": user_oid})


@pytest.fixture
def db():
    return get_sync_db()


# ---------------------------------------------------------------------------
# Message builder unit tests (no DB, no network)
# ---------------------------------------------------------------------------

class TestTelegramAlertBuilder:
    def test_contains_route(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "rule": {"type": "threshold", "threshold_price": 100.0},
            "last_offer": {"airline": "VY", "airline_name": "Vueling",
                           "stops": 0, "duration_min": 195, "deep_link": None},
        }
        text = _build_telegram_alert(watch, price=85.0, rule_type="threshold")
        assert "RIX" in text
        assert "BCN" in text

    def test_contains_price(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "rule": {"type": "new_low"},
            "last_offer": None,
        }
        text = _build_telegram_alert(watch, price=88.0, rule_type="new_low")
        assert "88" in text

    def test_fallback_search_link_when_deep_link_none(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "rule": {"type": "new_low"},
            "last_offer": {"airline": "VY", "airline_name": "Vueling",
                           "stops": 0, "duration_min": 100, "deep_link": None},
        }
        text = _build_telegram_alert(watch, price=88.0, rule_type="new_low")
        assert "Забронировать" not in text
        assert "Найти билет" in text
        assert "google.com/travel/flights" in text

    def test_real_deep_link_uses_book_label(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "rule": {"type": "new_low"},
            "last_offer": {"airline": "VY", "airline_name": "Vueling",
                           "stops": 0, "duration_min": 100,
                           "deep_link": "https://example.com/book"},
        }
        text = _build_telegram_alert(watch, price=88.0, rule_type="new_low")
        assert "Забронировать" in text
        assert "example.com/book" in text

    def test_digest_contains_route(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "lowest_seen": 75.0,
            "last_offer": {"price": 85.0},
        }
        text = _build_telegram_digest(watch)
        assert "RIX" in text
        assert "BCN" in text
        assert "85" in text
        assert "75" in text

    def test_digest_no_data_when_offer_none(self):
        watch = {
            "_id": ObjectId(), "origin": "RIX", "destination": "BCN",
            "depart_date": "2026-09-15",
            "lowest_seen": None,
            "last_offer": None,
        }
        text = _build_telegram_digest(watch)
        assert "нет данных" in text


# ---------------------------------------------------------------------------
# send_alert service tests
# ---------------------------------------------------------------------------

class TestSendAlert:
    def test_no_channel_inserts_failed_alert(self, db):
        user = _make_user(db, plan="free", telegram_chat_id=None)
        watch = _make_watch(db, user["_id"])
        try:
            send_alert(watch, user, price=85.0, rule_type="threshold")
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert is not None
            assert alert["status"] == "failed"
            assert alert["error"] == "no_channel"
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_telegram_success_inserts_sent_alert(self, db):
        user = _make_user(db, telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg:
                send_alert(watch, user, price=85.0, rule_type="threshold")
            mock_tg.assert_called_once()
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert["status"] == "sent"
            assert alert["channel"] == "telegram"
            assert alert["price"] == 85.0
            assert alert["rule_type"] == "threshold"
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_telegram_failure_records_failed_alert(self, db):
        user = _make_user(db, telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_telegram",
                       side_effect=ValueError("Telegram 403: bot blocked")):
                send_alert(watch, user, price=85.0, rule_type="threshold")
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert["status"] == "failed"
            assert "telegram" in alert["error"]
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_email_sent_for_pro_plan(self, db):
        user = _make_user(db, plan="pro", telegram_chat_id=None)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_email") as mock_em:
                send_alert(watch, user, price=85.0, rule_type="new_low")
            mock_em.assert_called_once()
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert["status"] == "sent"
            assert alert["channel"] == "email"
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_both_channels_one_fails_partial(self, db):
        user = _make_user(db, plan="pro", telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg, \
                 patch("app.services.notifier._send_via_email",
                       side_effect=ValueError("SMTP error")):
                send_alert(watch, user, price=85.0, rule_type="threshold")
            mock_tg.assert_called_once()
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert["status"] == "partial"
            assert alert["channel"] == "both"
            assert "email" in alert["error"]
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_updates_last_alerted_at_on_watch(self, db):
        user = _make_user(db, telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"])
        assert watch["last_alerted_at"] is None
        try:
            with patch("app.services.notifier._send_via_telegram"):
                send_alert(watch, user, price=85.0, rule_type="threshold")
            updated = db.watches.find_one({"_id": watch["_id"]})
            assert updated["last_alerted_at"] is not None
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_free_plan_no_email(self, db):
        # free plan should not send email even if telegram fails
        user = _make_user(db, plan="free", telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg, \
                 patch("app.services.notifier._send_via_email") as mock_em:
                send_alert(watch, user, price=85.0, rule_type="threshold")
            mock_tg.assert_called_once()
            mock_em.assert_not_called()
            alert = db.alerts.find_one({"watch_id": watch["_id"]})
            assert alert["channel"] == "telegram"
        finally:
            _cleanup(db, user["_id"], watch["_id"])


# ---------------------------------------------------------------------------
# send_digest service tests
# ---------------------------------------------------------------------------

class TestSendDigest:
    def test_sends_digest_and_inserts_alert(self, db):
        user = _make_user(db, telegram_chat_id=111222)
        watch = _make_watch(db, user["_id"], rule={"type": "digest", "digest_time": "08:00"})
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg:
                send_digest(watch, user)
            mock_tg.assert_called_once()
            alert = db.alerts.find_one({"watch_id": watch["_id"], "rule_type": "digest"})
            assert alert is not None
            assert alert["status"] == "sent"
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_no_channel_skips_silently(self, db):
        user = _make_user(db, plan="free", telegram_chat_id=None)
        watch = _make_watch(db, user["_id"])
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg:
                send_digest(watch, user)
            mock_tg.assert_not_called()
            assert db.alerts.find_one({"watch_id": watch["_id"]}) is None
        finally:
            _cleanup(db, user["_id"], watch["_id"])

    def test_digest_with_no_last_offer(self, db):
        user = _make_user(db, telegram_chat_id=111222)
        oid = ObjectId()
        now = datetime.now(timezone.utc)
        db.watches.insert_one({
            "_id": oid, "user_id": user["_id"], "origin": "RIX",
            "destination": "BCN", "date_mode": "exact", "depart_date": "2026-09-15",
            "rule": {"type": "digest", "digest_time": "08:00"}, "active": True,
            "lowest_seen": None, "lowest_seen_at": None, "last_checked_at": None,
            "last_alerted_at": None, "last_offer": None,
            "created_at": now, "updated_at": now,
        })
        watch = db.watches.find_one({"_id": oid})
        try:
            with patch("app.services.notifier._send_via_telegram") as mock_tg:
                send_digest(watch, user)
            mock_tg.assert_called_once()
            call_text = mock_tg.call_args[0][1]
            assert "нет данных" in call_text
        finally:
            _cleanup(db, user["_id"], oid)


# ---------------------------------------------------------------------------
# Alerts API endpoint tests
# ---------------------------------------------------------------------------

def _auth_headers(user: dict) -> dict:
    token = create_access_token(str(user["_id"]), user.get("plan", "free"))
    return {"Authorization": f"Bearer {token}"}


def _insert_alert(db, watch_oid: ObjectId, user_oid: ObjectId, rule_type: str = "threshold") -> ObjectId:
    oid = ObjectId()
    now = datetime.now(timezone.utc)
    db.alerts.insert_one({
        "_id": oid,
        "watch_id": watch_oid,
        "user_id": user_oid,
        "rule_type": rule_type,
        "triggered_at": now,
        "price": 85.0,
        "offer": None,
        "channel": "telegram",
        "status": "sent",
        "error": None,
        "created_at": now,
    })
    return oid


@pytest.mark.asyncio
async def test_list_alerts_returns_own_alerts(db):
    user = _make_user(db, telegram_chat_id=111)
    watch = _make_watch(db, user["_id"])
    alert_oid = _insert_alert(db, watch["_id"], user["_id"])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/alerts", headers=_auth_headers(user))
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        assert any(a["alert_id"] == str(alert_oid) for a in data)
    finally:
        db.alerts.delete_many({"watch_id": watch["_id"]})
        _cleanup(db, user["_id"], watch["_id"])


@pytest.mark.asyncio
async def test_list_alerts_filtered_by_watch_id(db):
    user = _make_user(db, telegram_chat_id=111)
    watch1 = _make_watch(db, user["_id"])
    watch2 = _make_watch(db, user["_id"])
    a1 = _insert_alert(db, watch1["_id"], user["_id"])
    a2 = _insert_alert(db, watch2["_id"], user["_id"])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(
                f"/api/v1/alerts?watch_id={watch1['_id']}",
                headers=_auth_headers(user),
            )
        assert r.status_code == 200
        ids = [a["alert_id"] for a in r.json()]
        assert str(a1) in ids
        assert str(a2) not in ids
    finally:
        db.alerts.delete_many({"user_id": user["_id"]})
        _cleanup(db, user["_id"], watch1["_id"])
        _cleanup(db, user["_id"], watch2["_id"])


@pytest.mark.asyncio
async def test_list_alerts_empty_for_new_user(db):
    user = _make_user(db, telegram_chat_id=111)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/alerts", headers=_auth_headers(user))
        assert r.status_code == 200
        assert r.json() == []
    finally:
        db.users.delete_one({"_id": user["_id"]})


@pytest.mark.asyncio
async def test_list_alerts_requires_auth(db):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/api/v1/alerts")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_alert_by_id(db):
    user = _make_user(db, telegram_chat_id=111)
    watch = _make_watch(db, user["_id"])
    alert_oid = _insert_alert(db, watch["_id"], user["_id"])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/api/v1/alerts/{alert_oid}", headers=_auth_headers(user))
        assert r.status_code == 200
        data = r.json()
        assert data["alert_id"] == str(alert_oid)
        assert data["rule_type"] == "threshold"
        assert data["status"] == "sent"
    finally:
        db.alerts.delete_many({"watch_id": watch["_id"]})
        _cleanup(db, user["_id"], watch["_id"])


@pytest.mark.asyncio
async def test_get_alert_wrong_owner_returns_403(db):
    user1 = _make_user(db, telegram_chat_id=111)
    user2 = _make_user(db, telegram_chat_id=222)
    watch = _make_watch(db, user1["_id"])
    alert_oid = _insert_alert(db, watch["_id"], user1["_id"])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(
                f"/api/v1/alerts/{alert_oid}", headers=_auth_headers(user2)
            )
        assert r.status_code == 403
    finally:
        db.alerts.delete_many({"watch_id": watch["_id"]})
        _cleanup(db, user1["_id"], watch["_id"])
        db.users.delete_one({"_id": user2["_id"]})


@pytest.mark.asyncio
async def test_get_alert_not_found_returns_404(db):
    user = _make_user(db, telegram_chat_id=111)
    fake_id = str(ObjectId())
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/api/v1/alerts/{fake_id}", headers=_auth_headers(user))
        assert r.status_code == 404
    finally:
        db.users.delete_one({"_id": user["_id"]})


@pytest.mark.asyncio
async def test_list_alerts_does_not_leak_other_users_alerts(db):
    user1 = _make_user(db, telegram_chat_id=111)
    user2 = _make_user(db, telegram_chat_id=222)
    watch1 = _make_watch(db, user1["_id"])
    _insert_alert(db, watch1["_id"], user1["_id"])
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/alerts", headers=_auth_headers(user2))
        assert r.status_code == 200
        assert r.json() == []
    finally:
        db.alerts.delete_many({"watch_id": watch1["_id"]})
        _cleanup(db, user1["_id"], watch1["_id"])
        db.users.delete_one({"_id": user2["_id"]})
