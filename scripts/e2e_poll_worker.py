# -*- coding: ascii -*-
"""
End-to-end live test for S5 poll-worker.

Runs against the full stack (api + worker + mongo + redis).
Does NOT use pytest -- it is a standalone smoke-test script.

Usage:
    docker compose up -d api worker mongo redis
    python scripts/e2e_poll_worker.py

Exit code 0 = all checks passed, 1 = something failed.
"""
import sys
import time

import requests

BASE = "http://localhost:8000/api/v1"
EMAIL = "e2e_test_{}@example.com".format(int(time.time()))
PASSWORD = "Test1234!"

errors = []


def ok(msg):
    print("  [OK]   " + msg)


def fail(msg):
    print("  [FAIL] " + msg)
    errors.append(msg)


def info(msg):
    print("  [..]   " + msg)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def register():
    r = requests.post(BASE + "/auth/register", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 201:
        ok("registered " + EMAIL)
    else:
        fail("register -> " + str(r.status_code) + ": " + r.text)


def login():
    r = requests.post(BASE + "/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 200:
        token = r.json()["access_token"]
        ok("login -> got JWT")
        return token
    fail("login -> " + str(r.status_code) + ": " + r.text)
    return ""


def auth_headers(token):
    return {"Authorization": "Bearer " + token}


def create_watch(token):
    payload = {
        "origin": "RIX",
        "destination": "BCN",
        "date_mode": "exact",
        "depart_date": "2026-09-15",
        "passengers": 1,
        "cabin": "economy",
        "rule": {"type": "threshold", "threshold_price": 9999},
    }
    r = requests.post(BASE + "/watches", json=payload, headers=auth_headers(token))
    if r.status_code == 201:
        data = r.json()
        wid = data["watch_id"]
        ok("watch created -> " + wid)
        return wid
    fail("create_watch -> " + str(r.status_code) + ": " + r.text)
    return ""


def wait_for_poll(token, watch_id, timeout=30):
    """Poll GET /watches/{id} until last_checked_at is set."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(BASE + "/watches/" + watch_id, headers=auth_headers(token))
        if r.status_code == 200:
            data = r.json()
            if data.get("last_checked_at"):
                return data
        time.sleep(1)
    return None


# ---------------------------------------------------------------------------
# test steps
# ---------------------------------------------------------------------------

def test_auto_poll_on_create(token, watch_id):
    print("\n[1] Auto-poll triggered on watch creation")
    info("waiting up to 30s for worker to process watch " + watch_id + "...")

    watch = wait_for_poll(token, watch_id, timeout=30)
    if watch is None:
        fail("worker did not set last_checked_at within 30s")
        return

    ok("last_checked_at = " + str(watch["last_checked_at"]))

    if watch["lowest_seen"] is not None:
        ok("lowest_seen = " + str(watch["lowest_seen"]) + " EUR")
    else:
        fail("lowest_seen is still None after poll")

    if watch["lowest_seen_at"] is not None:
        ok("lowest_seen_at = " + str(watch["lowest_seen_at"]))
    else:
        fail("lowest_seen_at is still None after poll")

    lo = watch.get("last_offer")
    if lo:
        ok("last_offer: {} @ {} EUR, {} stop(s)".format(lo["airline"], lo["price"], lo["stops"]))
    else:
        fail("last_offer is None after successful poll")


def test_snapshots_written(token, watch_id):
    print("\n[2] Snapshot written to price_snapshots")
    r = requests.get(BASE + "/watches/" + watch_id + "/snapshots", headers=auth_headers(token))
    if r.status_code != 200:
        fail("GET snapshots -> " + str(r.status_code) + ": " + r.text)
        return

    snaps = r.json()
    if not snaps:
        fail("no snapshots found in price_snapshots")
        return

    ok("{} snapshot(s) found".format(len(snaps)))
    s = snaps[0]
    ok("first snapshot: price={} airline={} stops={}".format(s["price"], s["airline"], s["stops"]))

    if s["price"] is not None and s["price"] > 0:
        ok("price is a positive number")
    else:
        fail("unexpected price value: " + str(s["price"]))

    if s["airline"] in {"W6", "VY", "FR"}:
        ok("airline '{}' is a known mock airline".format(s["airline"]))
    else:
        fail("unknown airline: " + str(s["airline"]))


def test_manual_check_endpoint(token, watch_id):
    print("\n[3] Manual /check endpoint triggers another poll")
    r = requests.post(BASE + "/watches/" + watch_id + "/check", headers=auth_headers(token))
    if r.status_code == 202:
        job_id = r.json().get("job_id")
        ok("202 Accepted -- Celery job_id = " + str(job_id))
    else:
        fail("POST /check -> " + str(r.status_code) + ": " + r.text)
        return

    info("waiting 15s for second poll to complete...")
    time.sleep(15)

    r2 = requests.get(BASE + "/watches/" + watch_id + "/snapshots", headers=auth_headers(token))
    snaps = r2.json() if r2.status_code == 200 else []
    if len(snaps) >= 2:
        ok("{} snapshots total after manual check".format(len(snaps)))
    else:
        fail("expected >=2 snapshots after manual check, got " + str(len(snaps)))


def test_check_cooldown(token, watch_id):
    print("\n[4] Cooldown: second /check within 5 min -> 429")
    r = requests.post(BASE + "/watches/" + watch_id + "/check", headers=auth_headers(token))
    if r.status_code == 429:
        body = r.json()
        # FastAPI wraps detail: {"detail": {...}} or {"detail": "string"}
        detail = body.get("detail", {})
        retry_after = detail.get("retry_after") if isinstance(detail, dict) else None
        ok("429 Too Many Requests -- retry_after = " + str(retry_after) + "s")
    else:
        fail("expected 429 from cooldown, got " + str(r.status_code) + ": " + r.text)


def test_lowest_seen_is_min(token, watch_id):
    print("\n[5] lowest_seen is the minimum across all snapshots")
    snap_r = requests.get(BASE + "/watches/" + watch_id + "/snapshots", headers=auth_headers(token))
    watch_r = requests.get(BASE + "/watches/" + watch_id, headers=auth_headers(token))

    if snap_r.status_code != 200 or watch_r.status_code != 200:
        fail("could not fetch data to check lowest_seen")
        return

    prices = [s["price"] for s in snap_r.json() if s["price"] is not None]
    lowest_seen = watch_r.json().get("lowest_seen")

    if not prices:
        fail("no valid prices in snapshots")
        return

    actual_min = min(prices)
    if lowest_seen == actual_min:
        ok("lowest_seen = {} == min of {} snapshot prices".format(lowest_seen, len(prices)))
    else:
        fail("lowest_seen = {} but min snapshot price = {}".format(lowest_seen, actual_min))


def test_authz_other_user(token, watch_id):
    print("\n[6] AuthZ: another user cannot read or poll the watch")
    other_email = "e2e_other_{}@example.com".format(int(time.time()))
    requests.post(BASE + "/auth/register", json={"email": other_email, "password": PASSWORD})
    r = requests.post(BASE + "/auth/login", json={"email": other_email, "password": PASSWORD})
    if r.status_code != 200:
        fail("could not create other user for authz test")
        return
    other_token = r.json()["access_token"]
    other_hdrs = auth_headers(other_token)

    get_r = requests.get(BASE + "/watches/" + watch_id, headers=other_hdrs)
    if get_r.status_code == 403:
        ok("GET watch by other user -> 403 Forbidden")
    else:
        fail("expected 403 for GET by other user, got " + str(get_r.status_code))

    check_r = requests.post(BASE + "/watches/" + watch_id + "/check", headers=other_hdrs)
    if check_r.status_code == 403:
        ok("POST /check by other user -> 403 Forbidden")
    else:
        fail("expected 403 for /check by other user, got " + str(check_r.status_code))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("=" * 58)
    print("  FareWatch S5 poll-worker -- end-to-end smoke test")
    print("=" * 58)

    print("\n[0] Setup: register + login + create watch")
    register()
    token = login()
    if not token:
        print("\nABORTED: could not authenticate")
        return 1

    watch_id = create_watch(token)
    if not watch_id:
        print("\nABORTED: could not create watch")
        return 1

    test_auto_poll_on_create(token, watch_id)
    test_snapshots_written(token, watch_id)
    test_manual_check_endpoint(token, watch_id)
    test_check_cooldown(token, watch_id)
    test_lowest_seen_is_min(token, watch_id)
    test_authz_other_user(token, watch_id)

    print("\n" + "=" * 58)
    if errors:
        print("  FAILED -- {} check(s) failed:".format(len(errors)))
        for e in errors:
            print("    [FAIL] " + e)
        return 1
    else:
        print("  ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
