# FareWatch — TODO / Статус реализации

> Актуально на 2026-06-30. Сверяться с `SPEC.md` перед реализацией каждого пункта.
> Статус выставлен после ручного чтения каждого файла — не по памяти.

---

## Легенда

| Символ | Смысл |
|---|---|
| ✅ | Реализовано полностью |
| 🔶 | Есть код, но есть конкретные пробелы — описаны ниже |
| ❌ | Файл — заглушка (один комментарий, без кода) |

---

## §1 auth — 🔶 Почти готово

Файлы: `api/auth.py`, `models/user.py`, `core/security.py`, `services/authz.py`

| Эндпоинт | Статус |
|---|---|
| POST `/api/v1/auth/register` | ✅ |
| POST `/api/v1/auth/login` | ✅ |
| GET `/api/v1/auth/me` | ✅ |
| PATCH `/api/v1/auth/me` | 🔶 см. ниже |
| POST `/api/v1/auth/change-password` | ✅ |
| DELETE `/api/v1/auth/me` (каскад) | ✅ |

**Пробелы в `PATCH /me`:**
- `PatchMeRequest` содержит только `telegram_chat_id`. SPEC §1.3 говорит «Обновляет профиль (Telegram, email)» — поле `email` не поддерживается.
- Условие `if body.telegram_chat_id is not None` не даёт отвязать Telegram (передать `null`). SPEC §1.4 экран настроек подразумевает возможность отключения.

---

## §2 watches — 🔶 Почти готово

Файлы: `api/watches.py`, `models/watch.py`

| Эндпоинт | Статус |
|---|---|
| POST `/api/v1/watches` | ✅ |
| GET `/api/v1/watches` | ✅ |
| GET `/api/v1/watches/{id}` | ✅ |
| PATCH `/api/v1/watches/{id}` | ✅ |
| DELETE `/api/v1/watches/{id}` | ✅ |
| POST `/api/v1/watches/{id}/check` | ✅ cooldown Redis 5 мин |
| GET `/api/v1/watches/{id}/snapshots` | ✅ |

**Пробел:**
- `POST /watches` вызывает `celery_app.send_task("app.workers.tasks.poll_watch", ...)` — задача теперь зарегистрирована (§4), но выполняется как заглушка (warning). Полная работа — после §5.

---

## §3 provider — ✅ Готово

Файлы: `providers/base.py`, `providers/mock.py`, `providers/amadeus.py`, `providers/__init__.py`

| Компонент | Статус |
|---|---|
| `SearchParams`, `Offer` dataclasses | ✅ |
| Исключения `ProviderTimeout`, `ProviderError`, `NoOffersFound` | ✅ |
| `FareProvider` (ABC) | ✅ |
| `MockProvider` — детерм. цена, шум ±15%, range mode | ✅ |
| `AmadeusProvider` — OAuth2, Redis TTL-кэш, rate-limit, retry 4× | ✅ |
| `get_provider()` фабрика | ✅ |
| Тесты (13/13) | ✅ `tests/test_providers.py` |

---

## §4 scheduler — ✅ Готово

Файлы: `workers/celery_app.py`, `workers/beat_schedule.py`, `workers/tasks.py`, `core/db.py`

| Компонент | Статус | Проверено вживую |
|---|---|---|
| `celery_app.py` — `include=["app.workers.tasks"]`, `beat_schedule` | ✅ | worker показывает все 3 задачи в `[tasks]` |
| `beat_schedule.py` — `fan_out_polls` + `send_digests` crontab(minute=0) | ✅ | `inspect conf` подтверждает загрузку |
| `fan_out_polls` — Redis NX-lock, N+1-free user cache, due-расчёт по плану, stagger 30 мин, `scheduler:last_run` | ✅ | 2 watches найдены и dispatched |
| Идемпотентность lock — второй вызов в течение TTL блокируется | ✅ | "lock held by another instance, skipping" |
| Stagger — `countdown = i * (1800/n)` секунд | ✅ | второй watch отложен на 900 с (15 мин) |
| `send_digests` — фильтр `rule.digest_time == "HH:00"`, вызов `evaluate_digest` | ✅ | отработал без ошибок |
| `core/db.py` — `get_sync_db()` / `get_sync_client()` для pymongo | ✅ | |
| `poll_watch` — зарегистрирован (заглушка, воркер не падает) | 🔶 | полная реализация в §5 |

**Найден и исправлен баг (во время проверки):**
- `models/watch.py` — валидатор `RuleIn` принимал `digest_time` в формате `"HH:MM"` (например `"08:30"`), но `send_digests` матчит только `"HH:00"` (scheduler hourly). Пользователь с `"08:30"` никогда не получил бы дайджест.
- **Исправление:** regex изменён с `^\d{2}:\d{2}$` на `^\d{2}:00$`. Проверено: `"08:30"` → 422, `"08:00"` → 201.

**Замечание по архитектуре:**
- `send_digests` вызывает `rules_engine.evaluate_digest(watch)`, а не `notifier.send_digest(watch)` напрямую (как написано в §4.5 SPEC). Это соответствует §6.3 ("evaluate_digest вызывается scheduler'ом") и правильно — cooldown проверяется внутри evaluate_digest. Расхождение в SPEC, не в коде.

---

## §5 poll-worker — ✅ Готово

Файлы: `workers/tasks.py` (задача `poll_watch`), `services/price_service.py`

| Компонент | Статус | Проверено |
|---|---|---|
| `poll_watch` — декоратор `bind=True`, `autoretry_for=(ProviderTimeout, ProviderError)`, `retry_backoff` | ✅ | 15/15 тестов |
| Загрузка watch + проверка `active` / `None` | ✅ | тест skips_inactive, skips_nonexistent |
| Загрузка user по `user_id` | ✅ | |
| `SearchParams` из полей watch (`exact` + `range`) | ✅ | |
| `provider.search(params)` + no-offers path → `write_snapshot(null)` + `mark_checked` | ✅ | |
| `write_snapshot` → time-series `price_snapshots` | ✅ | тест TestWriteSnapshot |
| Атомарный `$min lowest_seen` через aggregation pipeline (`$ifNull` — см. ниже) | ✅ | тест sets_lowest_seen_on_first_poll |
| `lowest_seen_at` — только при новом минимуме (через `returnDocument=BEFORE`) | ✅ | тест does_not_update_lowest_seen_at_when_higher |
| `cache_last_price` → `HSET lastprice:{watch_id}` + `EXPIRE` | ✅ | тест TestCacheLastPrice |
| `rules_engine.evaluate(...)` вызывается (stub, §6) | ✅ | |
| Тесты (15/15) | ✅ | `tests/test_poll_worker.py` |

**Найден и исправлен баг (при тестировании):**
- MongoDB `$min` трактует `null` как значение, меньшее любого числа. При первом поле `$min(null, 87.5)` оставляет `null`, а не пишет 87.5.
- **Исправление:** plain `$min` заменён на aggregation pipeline update с `$min: [price, $ifNull: [$lowest_seen, price]]`.
- Теперь при `lowest_seen=null` пишется первое значение; при числовом — берётся минимум.

---

## §6 rules-engine — ❌ Заглушка

Файл `services/rules_engine.py` — одна строка комментария, кода нет.

### Что нужно реализовать

**`evaluate(watch, current_price, old_lowest) -> bool`**
- [ ] `threshold`: `fired = current_price <= rule.threshold_price`
- [ ] `new_low`: `fired = old_lowest is None or current_price < old_lowest`
- [ ] `drop_pct`: найти предыдущий снэпшот (skip=1, `price != null`); `drop = (prev - cur) / prev * 100`; `fired = drop >= rule.drop_pct`
- [ ] `digest`: `fired = False`
- [ ] Проверить Redis cooldown `cooldown:{watch_id}:{rule_type}` — если ключ есть, подавить (return False)
- [ ] `SET NX` cooldown атомарно
- [ ] `notifier.send_alert(watch, user, price, rule_type)`

**`evaluate_digest(watch) -> None`**
- [ ] Собрать данные: `last_offer.price`, `lowest_seen`, `last_checked_at`
- [ ] Cooldown `cooldown:{watch_id}:digest` (20 ч)
- [ ] `notifier.send_digest(watch, user)`

**Константы (SPEC §6.5):**
```python
COOLDOWN = {"threshold": 86400, "new_low": 43200, "drop_pct": 43200, "digest": 72000}
```

---

## §7 notifier — ❌ Заглушка

Три файла — заглушки:
- `services/notifier.py` — одна строка комментария
- `api/alerts.py` — одна строка комментария
- `api/integrations.py` — одна строка комментария

Дополнительно: **`main.py` не регистрирует `alerts_router` и `integrations_router`** — даже когда роутеры будут написаны, их нужно добавить в `app.include_router(...)`.

### Что нужно реализовать

**`services/notifier.py` — `send_alert(watch, user, price, rule_type)`**
- [ ] `telegram_ok = user.telegram_chat_id is not None`
- [ ] `email_ok = user.plan in ["pro", "team"]`
- [ ] Если оба False → запись `alert` со `status="failed"`, `error="no_channel"`, выйти
- [ ] Создать `alert` документ в `alerts` (`status="pending"`)
- [ ] Telegram: `POST https://api.telegram.org/bot{TOKEN}/sendMessage` (MarkdownV2, шаблон из SPEC §7.5)
- [ ] Email: SMTP через `smtplib`; HTML-шаблон Jinja2
- [ ] Итоговый статус: `"sent"` / `"partial"` / `"failed"`
- [ ] Обновить `alert.status`, `alert.error`; `watches.last_alerted_at = now`

**`services/notifier.py` — `send_digest(watch, user)`**
- [ ] Дайджест-шаблон (SPEC §7.5)
- [ ] Cooldown `cooldown:{watch_id}:digest` 20 ч

**`api/alerts.py`**
- [ ] `GET /api/v1/alerts` — `watch_id?`, `limit`, `offset`; фильтр по `user_id` из JWT
- [ ] `GET /api/v1/alerts/{alert_id}` — проверка `user_id`, 403 если чужой

**`api/integrations.py`**
- [ ] Эндпоинт с инструкцией подключения Telegram (опционально для MVP)

**`models/`**
- [ ] Добавить `AlertResponse` Pydantic-модель

**`main.py`**
- [ ] `app.include_router(alerts_router, prefix="/api/v1")`
- [ ] `app.include_router(integrations_router, prefix="/api/v1")` (если MVP)

---

## §8 dashboard (Frontend) — ❌ Не начато

`frontend/.gitkeep` — директория пустая.

### Что нужно реализовать

**Инициализация**
- [ ] `npm create vite@latest frontend -- --template react-ts`
- [ ] Зависимости: `tailwindcss`, `recharts`, `date-fns`, `axios`, `react-router-dom`
- [ ] Dockerfile для frontend + nginx

**Инфраструктура**
- [ ] Axios-interceptor: `Authorization: Bearer` из localStorage + 401 → redirect `/login`
- [ ] `AuthContext` / Zustand: `token`, `plan`, `email`, `telegramConnected`
- [ ] Protected routes

**Страницы**
- [ ] `/login` — форма, JWT в localStorage, redirect `/watches`
- [ ] `/register` — форма, ссылка на `/login`
- [ ] `/watches` — список карточек (skeleton / empty / plan_limit / populated)
- [ ] `/watches/new` — пошаговая форма (маршрут → даты → пассажиры → правило)
- [ ] `/watches/:id` — текущая цена, all-time low, график Recharts, лог алертов
- [ ] `/settings` — профиль, Telegram, смена пароля, danger zone

**Компоненты**
- [ ] Карточка watch: маршрут, цена-badge, last_checked relative time, правило-badge, кнопки ▶/⏸/🔄/🗑
- [ ] График `LineChart`: X=datetime, Y=price EUR, threshold/lowest линии, разрывы при `null`, tooltip
- [ ] `formatDistanceToNow` (date-fns, locale ru) для относительного времени

---

## Инфраструктура

| Файл/задача | Статус | Примечание |
|---|---|---|
| `compose.yml` (api/worker/beat/mongo/redis) | ✅ | |
| `backend/Dockerfile` | ✅ | |
| MongoDB индексы + time-series `price_snapshots` | ✅ `core/db.py` | |
| `celery_app.py` — broker/backend, `include`, `beat_schedule` | ✅ | |
| `.github/workflows/ci.yml` | 🔶 | создан, не проверялся после новых файлов |
| Тесты §4–§7 | ❌ | |
| `frontend/Dockerfile` | ❌ | |
| nginx / reverse-proxy | ❌ вне MVP | |

---

## Порядок реализации (рекомендуемый)

```
celery_app.py fix  →  §4+§5  →  §6  →  §7  →  §8
(autodiscover)       scheduler   rules    notifier   frontend
                     + worker    engine
```

**§4/§5 блокируют всё**: без `poll_watch` нет снэпшотов → нет данных для rules-engine, notifier и графика dashboard.
