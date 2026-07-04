# FareWatch

A flight price tracker that monitors routes, fires alerts when prices drop, and shows a history chart.
Built as a portfolio project — pure engineering, no AI.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Pydantic v2 (async, Motor) |
| Workers | Celery + Celery Beat |
| Broker / Cache | Redis 7 |
| Database | MongoDB 7 (time-series for price history) |
| Auth | JWT HS256 + Argon2id |
| Fare data | Amadeus Self-Service API (mock provider in dev) |
| Notifications | Telegram Bot API + SMTP email |
| Frontend | React 18 + Vite + TypeScript + Recharts + Tailwind CSS |
| Infra | Docker Compose + GitHub Actions CI |

## Architecture

```
React (5173) → FastAPI /api/v1 (8000) → MongoDB
                                       → Redis  (broker · cache · cooldown keys)
                          Celery Worker ← Celery Beat (cron fan-out)
                                  ↓ FareProvider        ↓ Notifier
                              Amadeus / Mock         Telegram / Email
```

## Quick Start

```bash
# 1. Copy env and set your secrets
cp .env.example .env

# 2. Start everything
docker compose up --build

# Frontend → http://localhost:5173
# API docs → http://localhost:8000/docs
```

To stop:
```bash
docker compose down          # stop, keep data
docker compose down -v       # stop, delete data
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | JWT signing key (change in prod) |
| `FARE_PROVIDER` | No | `mock` (default) or `amadeus` |
| `AMADEUS_CLIENT_ID` | Prod | Amadeus API key |
| `AMADEUS_CLIENT_SECRET` | Prod | Amadeus API secret |
| `TELEGRAM_BOT_TOKEN` | Alerts | Token from @BotFather |
| `TELEGRAM_BOT_USERNAME` | Optional | Bot username (shown in Settings) |
| `SMTP_HOST` | Pro/Team | SMTP server for email alerts |
| `SMTP_USER` | Pro/Team | SMTP login |
| `SMTP_PASSWORD` | Pro/Team | SMTP password |

## Plans & Limits

| | Free | Pro | Team |
|---|---|---|---|
| Max watches | 3 | 30 | 150 |
| Poll interval | 12 h | 3 h | 1 h |
| Channels | Telegram | Telegram + Email | Telegram + Email |
| Price history | 30 days | 12 months | 24 months |

## Running Tests

```bash
# Start infra first
docker compose up -d mongo redis

# Run backend tests
docker compose run --rm api pytest app/tests/ -v
```

## Modules

| Module | Description |
|---|---|
| `auth` | Register / login / profile / password change |
| `watches` | CRUD, check-now, snapshot history |
| `provider` | Amadeus API + mock provider |
| `scheduler` | Celery Beat fan-out — dispatches poll tasks per plan interval |
| `poll-worker` | Fetches price, writes time-series snapshot, tracks all-time low |
| `rules-engine` | Threshold / new-low / drop-% / digest rules + Redis cooldown |
| `notifier` | Telegram + email dispatch, alert log in MongoDB |
| `dashboard` | React SPA — watch list, price chart, alert log, settings |

## API Docs

Swagger UI available at `http://localhost:8000/docs` when the API container is running.
