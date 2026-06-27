# FareWatch — CLAUDE.md

## Project
Pet/portfolio flight price tracker. Users create "watches" on routes with rules; Celery
workers poll prices via Amadeus API and fire Telegram/email alerts when conditions are met.
**No AI** in this project — pure engineering backend demo.

## Spec-First
`PROJECT_IDEA.md` → `SPEC.md` → code.
**Read the relevant SPEC.md section before implementing any module.** Each section defines
data models, API contracts, business logic, edge cases, and MongoDB/Redis key schemas.

## Stack
| Layer | Tech |
|---|---|
| API | FastAPI + Pydantic v2 |
| Workers | Celery + Celery Beat |
| Broker/Cache | Redis 7 |
| Database | MongoDB 7 (time-series for `price_snapshots`) |
| Auth | JWT HS256 + Argon2id |
| Fare data | Amadeus Self-Service API |
| Notifications | Telegram Bot API + SMTP |
| Frontend | React + Vite + TypeScript + Recharts + Tailwind |
| Infra | Docker Compose + GitHub Actions |

## Architecture
```
React → FastAPI (/api/v1) → MongoDB
                           → Redis (broker · cache · cooldown keys)
                      Celery Worker ← Celery Beat (cron fan-out)
                           ↓ FareProvider       ↓ Notifier
                           Amadeus/Mock          Telegram/Email
```

## 8 Modules (see SPEC.md for each)
`auth` · `watches` · `provider` · `scheduler` · `poll-worker` · `rules-engine` · `notifier` · `dashboard`

## Key Rules
- **Authz**: No DB-level RLS. Every query filters `user_id` from JWT (`services/authz`). Wrong owner → 403.
- **Currency**: EUR everywhere, stored as `float` (2 decimal places).
- **Time**: UTC everywhere; frontend converts to local.
- **Provider**: `FARE_PROVIDER=mock` in dev/tests; `amadeus` in prod.
- **`price_snapshots`**: MongoDB time-series collection — create with `timeseries={}` opts, not a plain collection.
- **Errors**: `{"error": "<code>", "detail": "<human>"}`. API prefix: `/api/v1/`.
- **Pagination**: `limit` (default 20, max 100) + `offset` (default 0).
- **Plans**: `free` (3 watches, 12 h) · `pro` (30, 3 h) · `team` (150, 1 h).

## MVP Scope (implement in order)
1. Auth (JWT register/login/me) + watches CRUD
2. MockProvider → `poll_watch` Celery task → `price_snapshots`
3. `threshold` rule → Telegram alert
4. `docker compose up` green end-to-end

## Repo Layout
```
backend/app/
  main.py          # FastAPI app factory
  core/            # config · db (mongo) · redis · security (JWT/Argon2)
  models/          # Pydantic documents
  api/             # routers: health · auth · watches · alerts · integrations
  providers/       # base · amadeus · mock
  services/        # authz · rules_engine · notifier · price_service
  workers/         # celery_app · tasks · beat_schedule
  tests/
frontend/          # React + Vite + TS (v2)
compose.yml        # api · worker · beat · redis · mongo
```

## Run Commands
```bash
# Start full stack
docker compose up --build

# Dev: API + infra only (hot-reload)
docker compose up api mongo redis

# Worker + Beat
docker compose up worker beat

# Tests
docker compose run --rm api pytest app/tests/ -v

# Logs
docker compose logs -f worker beat
```

## Env Vars  (`.env.example` → `.env`)
```
MONGO_URL=mongodb://mongo:27017
REDIS_URL=redis://redis:6379/0
SECRET_KEY=changeme-in-prod
FARE_PROVIDER=mock
AMADEUS_CLIENT_ID=
AMADEUS_CLIENT_SECRET=
TELEGRAM_BOT_TOKEN=
```
