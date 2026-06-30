# FareWatch — TODO / Implementation Status

> Last updated: 2026-06-30. Cross-check with `SPEC.md` before implementing any section.
> Status set after reading each file directly — not from memory.

---

## Legend

| Symbol | Meaning |
|---|---|
| OK | Fully implemented and tested |
| PARTIAL | Code exists but specific gaps documented below |
| STUB | File is a stub (comment only, no logic) |

---

## §1 auth — PARTIAL

Files: `api/auth.py`, `models/user.py`, `core/security.py`, `services/authz.py`

| Endpoint | Status |
|---|---|
| POST `/api/v1/auth/register` | OK |
| POST `/api/v1/auth/login` | OK |
| GET `/api/v1/auth/me` | OK |
| PATCH `/api/v1/auth/me` | PARTIAL — see gaps below |
| POST `/api/v1/auth/change-password` | OK |
| DELETE `/api/v1/auth/me` (cascade) | OK |

**Gaps in `PATCH /me`:**
- `PatchMeRequest` only accepts `telegram_chat_id`. SPEC §1.3 says "update profile (Telegram, email)" — `email` field not supported.
- Condition `if body.telegram_chat_id is not None` prevents unsetting Telegram (passing `null`). SPEC §1.4 settings screen implies the user can disconnect.

---

## §2 watches — OK

Files: `api/watches.py`, `models/watch.py`

| Endpoint | Status |
|---|---|
| POST `/api/v1/watches` | OK — triggers `poll_watch` via Celery |
| GET `/api/v1/watches` | OK |
| GET `/api/v1/watches/{id}` | OK |
| PATCH `/api/v1/watches/{id}` | OK |
| DELETE `/api/v1/watches/{id}` | OK — cascades snapshots + alerts |
| POST `/api/v1/watches/{id}/check` | OK — Redis 5-min cooldown, 429 on repeat |
| GET `/api/v1/watches/{id}/snapshots` | OK |

**Bug fixed during §4 work:**
- `RuleIn` validator accepted `digest_time` in `"HH:MM"` format (e.g. `"08:30"`) but `send_digests` only matches `"HH:00"`. Fixed regex to `^\d{2}:00$`. Verified: `"08:30"` -> 422, `"08:00"` -> 201.

---

## §3 provider — OK

Files: `providers/base.py`, `providers/mock.py`, `providers/amadeus.py`, `providers/__init__.py`

| Component | Status |
|---|---|
| `SearchParams`, `Offer` dataclasses | OK |
| `ProviderTimeout`, `ProviderError`, `NoOffersFound` | OK |
| `FareProvider` ABC | OK |
| `MockProvider` — deterministic price, ±15% noise, range mode | OK |
| `AmadeusProvider` — OAuth2, Redis TTL cache, rate-limit, 4x retry | OK |
| `get_provider()` factory | OK |
| Tests (13/13) | OK — `tests/test_providers.py` |

---

## §4 scheduler — OK

Files: `workers/celery_app.py`, `workers/beat_schedule.py`, `workers/tasks.py`, `core/db.py`

| Component | Status | Verified live |
|---|---|---|
| `celery_app.py` — broker, include, beat_schedule | OK | worker shows all 3 tasks in [tasks] |
| `beat_schedule.py` — fan_out_polls + send_digests crontab(minute=0) | OK | confirmed via inspect conf |
| `fan_out_polls` — Redis NX-lock, N+1-free user cache, due calc, 30-min stagger | OK | 2 watches dispatched |
| Idempotency lock — second call within TTL is blocked | OK | "lock held by another instance" |
| `send_digests` — filters `rule.digest_time == "HH:00"`, calls `evaluate_digest` | OK | ran without error |
| `core/db.py` — `get_sync_db()` / `get_sync_client()` for Celery (pymongo) | OK | |

---

## §5 poll-worker — OK

Files: `workers/tasks.py` (task `poll_watch`), `services/price_service.py`

| Component | Status | Verified |
|---|---|---|
| `poll_watch` — `bind=True`, `autoretry_for=(ProviderTimeout, ProviderError)`, `retry_backoff` | OK | 15/15 unit tests |
| Load watch + check `active` / `None` — exit silently | OK | skips_inactive, skips_nonexistent tests |
| Load user by `user_id` | OK | |
| Build `SearchParams` from watch fields (`exact` + `range` mode) | OK | |
| `provider.search(params)` + no-offers path -> `write_snapshot(null)` + `mark_checked` | OK | |
| `write_snapshot` -> time-series `price_snapshots` | OK | TestWriteSnapshot |
| Atomic `lowest_seen` via aggregation pipeline + `$ifNull` (null-safe `$min`) | OK | sets_lowest_seen_on_first_poll |
| `lowest_seen_at` updated only when new minimum (via `returnDocument=BEFORE`) | OK | does_not_update_lowest_seen_at_when_higher |
| `cache_last_price` -> `HSET lastprice:{watch_id}` + `EXPIRE` with plan-based TTL | OK | TestCacheLastPrice |
| `rules_engine.evaluate(...)` called (stub until §6) | OK | |
| Unit tests (15/15) | OK | `tests/test_poll_worker.py` |
| E2E smoke test — full stack (api + worker + mongo + redis) | OK | `scripts/e2e_poll_worker.py` — all 6 checks pass |

**Bug found and fixed:**
- MongoDB `$min` treats `null` as less than any number — first-ever poll would keep `lowest_seen = null`. Fixed with aggregation pipeline: `$min: [price, $ifNull: [$lowest_seen, price]]`.

---

## §6 rules-engine — STUB

File: `services/rules_engine.py` — two stub functions, log warnings only.

### What to implement

**`evaluate(watch, current_price, old_lowest) -> bool`**
- [ ] `threshold`: `fired = current_price <= rule.threshold_price`
- [ ] `new_low`: `fired = old_lowest is None or current_price < old_lowest`
- [ ] `drop_pct`: fetch previous non-null snapshot (skip=1); `drop = (prev - cur) / prev * 100`; `fired = drop >= rule.drop_pct`
- [ ] `digest`: always `fired = False`
- [ ] Check Redis cooldown key `cooldown:{watch_id}:{rule_type}` — if present, suppress (return False)
- [ ] Set cooldown atomically with `SET NX`
- [ ] Load user from DB, call `notifier.send_alert(watch, user, price, rule_type)`
- [ ] Return True if alert was sent

**`evaluate_digest(watch) -> None`**
- [ ] Load user from DB
- [ ] Check cooldown `cooldown:{watch_id}:digest` (20 h)
- [ ] Call `notifier.send_digest(watch, user)`

**Cooldown constants (SPEC §6.5):**
```
COOLDOWN = {"threshold": 86400, "new_low": 43200, "drop_pct": 43200, "digest": 72000}
```

---

## §7 notifier — STUB

Three files are stubs:
- `services/notifier.py` — two stub functions
- `api/alerts.py` — one comment line
- `api/integrations.py` — one comment line

**`main.py` does NOT register `alerts_router` or `integrations_router`** — must add `app.include_router(...)` when those are implemented.

### What to implement

**`services/notifier.py` — `send_alert(watch, user, price, rule_type)`**
- [ ] `telegram_ok = user.telegram_chat_id is not None`
- [ ] `email_ok = user.plan in ["pro", "team"]`
- [ ] If both False -> insert alert with `status="failed"`, `error="no_channel"`, return
- [ ] Insert alert document (`status="pending"`) into `alerts` collection
- [ ] Telegram: POST `https://api.telegram.org/bot{TOKEN}/sendMessage` (MarkdownV2, template from SPEC §7.5)
- [ ] Email: SMTP via `smtplib`; Jinja2 HTML template
- [ ] Final status: `"sent"` / `"partial"` / `"failed"`
- [ ] Update `alert.status`, `alert.error`; set `watches.last_alerted_at = now`

**`services/notifier.py` — `send_digest(watch, user)`**
- [ ] Digest template (SPEC §7.5)

**`api/alerts.py`**
- [ ] `GET /api/v1/alerts` — optional `?watch_id=`, `limit`, `offset`; filter by `user_id` from JWT
- [ ] `GET /api/v1/alerts/{alert_id}` — check `user_id`, return 403 if wrong owner

**`api/integrations.py`**
- [ ] Telegram connect instructions endpoint (optional for MVP)

**`models/`**
- [ ] Add `AlertResponse` Pydantic model

**`main.py`**
- [ ] `app.include_router(alerts_router, prefix="/api/v1")`
- [ ] `app.include_router(integrations_router, prefix="/api/v1")` (if MVP)

---

## §8 dashboard (Frontend) — NOT STARTED

`frontend/` — only `.gitkeep`, nothing else.

### What to implement

**Init**
- [ ] `npm create vite@latest frontend -- --template react-ts`
- [ ] Dependencies: `tailwindcss`, `recharts`, `date-fns`, `axios`, `react-router-dom`
- [ ] Dockerfile for frontend + nginx

**Infrastructure**
- [ ] Axios interceptor: `Authorization: Bearer` from localStorage + 401 -> redirect `/login`
- [ ] `AuthContext` / Zustand: `token`, `plan`, `email`, `telegramConnected`
- [ ] Protected routes

**Pages**
- [ ] `/login` — form, JWT in localStorage, redirect `/watches`
- [ ] `/register` — form, link to `/login`
- [ ] `/watches` — list cards (skeleton / empty / plan_limit / populated)
- [ ] `/watches/new` — multi-step form (route -> dates -> passengers -> rule)
- [ ] `/watches/:id` — current price, all-time low, Recharts chart, alert log
- [ ] `/settings` — profile, Telegram, change password, danger zone

**Components**
- [ ] Watch card: route, price badge, last_checked relative time, rule badge, play/pause/refresh/delete buttons
- [ ] `LineChart`: X=datetime, Y=price EUR, threshold/lowest lines, null gaps, tooltip
- [ ] Relative timestamps via `date-fns` `formatDistanceToNow`

---

## Infrastructure

| File / Task | Status | Note |
|---|---|---|
| `compose.yml` (api / worker / beat / mongo / redis) | OK | |
| `backend/Dockerfile` | OK | |
| MongoDB indexes + time-series `price_snapshots` | OK | `core/db.py` |
| `celery_app.py` — broker, backend, beat_schedule, include | OK | |
| `.github/workflows/ci.yml` | OK | Fixed: added `cp .env.example .env` step; was failing with "env file not found" |
| Unit tests §1-§5 | OK | providers: 13/13, poll-worker: 15/15 |
| E2E smoke test §5 | OK | `scripts/e2e_poll_worker.py` |
| Tests §6-§7 | NOT STARTED | |
| `frontend/Dockerfile` | NOT STARTED | |
| nginx / reverse-proxy | NOT STARTED — out of MVP scope | |

---

## Recommended implementation order

```
§6 rules-engine  ->  §7 notifier  ->  §8 dashboard
  evaluate()          send_alert        React + Vite
  evaluate_digest()   alerts API        Recharts chart
  cooldown Redis      Telegram/email
```

**§6 and §7 unblock alerts end-to-end.** §8 (dashboard) can start independently once the API is stable.
