1# SPEC.md — FareWatch Technical Specification

> **Слой 2 (Техническая спецификация)** по методологии Spec-First.
> БД — MongoDB, авторизация — app-level по `user_id`, AI в проекте отсутствует.
> Источник: `PROJECT_IDEA.md`.

---

## Оглавление

1. [auth](#1-auth)
2. [watches](#2-watches)
3. [provider](#3-provider)
4. [scheduler](#4-scheduler)
5. [poll-worker](#5-poll-worker)
6. [rules-engine](#6-rules-engine)
7. [notifier](#7-notifier)
8. [dashboard](#8-dashboard)

---

## Глобальные соглашения

| Пункт | Значение |
|---|---|
| База данных | MongoDB (NoSQL) |
| Авторизация | JWT (HS256, 1 ч) проверяется в `services/authz`; `user_id` из токена сравнивается с `document.user_id` |
| Валюта | EUR (€) повсеместно; хранится как `float` (2 знака) |
| Время | UTC везде; клиент конвертирует в локальное |
| IATA-код | 3 символа, только заглавные латинские буквы |
| Версия API | `/api/v1/...` |
| Тип контента | `application/json` |
| Пагинация | query-параметры `limit` (default 20, max 100) + `offset` (default 0) |
| Ошибки | `{"error": "<code>", "detail": "<человекочитаемое>"}` |
| Планы | `"free"` · `"pro"` · `"team"` |

**Лимиты по планам:**

| Параметр | free | pro | team |
|---|---|---|---|
| Максимум watch'ей | 3 | 30 | 150 |
| Интервал опроса | 12 ч | 3 ч | 1 ч |
| Каналы уведомлений | Telegram | Telegram + email | Telegram + email |
| Длина хранимой истории | 30 дней | 12 мес | 24 мес |

---

## 1. auth

### 1.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| A-1 | Новый посетитель | Зарегистрироваться по email + паролю | Начать отслеживать рейсы |
| A-2 | Зарегистрированный пользователь | Войти и получить JWT | Использовать защищённые эндпоинты |
| A-3 | Аутентифицированный пользователь | Привязать Telegram chat_id | Получать алерты в Telegram |
| A-4 | Аутентифицированный пользователь | Сменить пароль | Обновить учётные данные |
| A-5 | Аутентифицированный пользователь | Получить свой профиль | Видеть план, статус Telegram, email |
| A-6 | Аутентифицированный пользователь | Удалить аккаунт и все данные | Полностью выйти из системы |

### 1.2 Модель данных

**Коллекция: `users`**

| Поле | Тип | Ограничения | По умолчанию |
|---|---|---|---|
| `_id` | `ObjectId` | PK | авто |
| `email` | `str` | уникальный, lowercase, max 254 | — |
| `password_hash` | `str` | Argon2id | — |
| `plan` | `str` | enum: `"free"` \| `"pro"` \| `"team"` | `"free"` |
| `telegram_chat_id` | `int \| null` | — | `null` |
| `telegram_connected_at` | `datetime \| null` | UTC | `null` |
| `created_at` | `datetime` | UTC | `now()` |
| `updated_at` | `datetime` | UTC | `now()` |

**Индексы:** `{email: 1}` (unique).

### 1.3 API

#### POST `/api/v1/auth/register`
Создаёт нового пользователя.

**Тело запроса:**
```json
{
  "email": "user@example.com",
  "password": "Str0ng!Pass"
}
```

**Ответ 201:**
```json
{
  "user_id": "64f1a2b3c4d5e6f7a8b9c0d1",
  "email": "user@example.com"
}
```

| Код | Причина |
|---|---|
| 201 | Создан |
| 409 | Email уже занят (`"error": "email_taken"`) |
| 422 | Валидация (слабый пароль, невалидный email) |

---

#### POST `/api/v1/auth/login`
Аутентификация, выдаёт JWT.

**Тело запроса:**
```json
{
  "email": "user@example.com",
  "password": "Str0ng!Pass"
}
```

**Ответ 200:**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Неверные учётные данные (`"error": "invalid_credentials"`) |
| 422 | Пустые поля |

---

#### GET `/api/v1/auth/me`
Возвращает профиль текущего пользователя.

**Заголовок:** `Authorization: Bearer <token>`

**Ответ 200:**
```json
{
  "user_id": "64f1a2b3c4d5e6f7a8b9c0d1",
  "email": "user@example.com",
  "plan": "free",
  "telegram_chat_id": 123456789,
  "telegram_connected_at": "2025-06-01T10:00:00Z",
  "created_at": "2025-05-15T08:00:00Z"
}
```

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Токен отсутствует или истёк |

---

#### PATCH `/api/v1/auth/me`
Обновляет профиль (Telegram, email).

**Тело (все поля опциональны):**
```json
{
  "telegram_chat_id": 123456789
}
```

**Ответ 200:** обновлённый профиль (та же схема, что GET `/me`).

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Не аутентифицирован |
| 422 | Невалидный `telegram_chat_id` (не целое число) |

---

#### POST `/api/v1/auth/change-password`
Меняет пароль после проверки старого.

**Тело:**
```json
{
  "old_password": "Str0ng!Pass",
  "new_password": "Newer!Pass2"
}
```

**Ответ 200:**
```json
{ "message": "password_changed" }
```

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Старый пароль неверен |
| 422 | Новый пароль не проходит политику |

---

#### DELETE `/api/v1/auth/me`
Удаляет аккаунт и все связанные данные (каскад).

**Ответ:** `204 No Content`

| Код | Причина |
|---|---|
| 204 | Удалено |
| 401 | Не аутентифицирован |

---

### 1.4 Экраны / Состояния

**Экран «Регистрация»** (`/register`)
- Поля: `email`, `password`, `confirm_password`
- Состояния: `idle` → `loading` → `success` (redirect `/watches`) | `error` (inline)
- Ошибки inline: email занят, пароль < 8 символов, пароли не совпадают

**Экран «Вход»** (`/login`)
- Поля: `email`, `password`
- Состояния: `idle` → `loading` → `success` (redirect) | `error` ("Неверный email или пароль")

**Экран «Настройки»** (`/settings`)
- Секция профиля: email (readonly), план (badge)
- Секция Telegram:
  - Статус: `"Подключён: chat_id XXXXXXX"` / `"Не подключён"`
  - Подключение: инструкция (запустить бота → `/start` → скопировать chat_id → вставить в поле → Save)
- Секция «Сменить пароль»: старый пароль, новый, подтверждение
- Danger zone: кнопка «Удалить аккаунт» → confirm-диалог

### 1.5 Бизнес-логика

1. **Нормализация email:** привести к lowercase перед хранением и поиском.
2. **Пароль:** минимум 8 символов; хэшируется Argon2id с параметрами по умолчанию библиотеки `argon2-cffi`.
3. **JWT:** payload `{"sub": "<user_id>", "exp": now+3600, "plan": "<plan>"}`. Секрет — из `settings.SECRET_KEY`. Алгоритм HS256.
4. **Валидация токена** (`services/authz`): декодировать JWT → получить `user_id` → каждый запрос к guard-эндпоинтам проверяет `user_id == document.user_id`.
5. **Регистрация:** после успешной записи в MongoDB клиент должен сделать POST `/login` самостоятельно (регистрация не возвращает токен).
6. **Каскадное удаление** (`DELETE /me`):
   - Получить все `watch_id` пользователя из `watches`
   - Удалить `price_snapshots` по `watch_id in [...]`
   - Удалить `alerts` по `watch_id in [...]`
   - Удалить все `watches` пользователя
   - Удалить документ `users`

### 1.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| Регистрация с уже существующим email | 409, `{"error": "email_taken"}` |
| Login с несуществующим email | 401 с тем же сообщением, что и неверный пароль (защита от enumeration) |
| Истёкший JWT | 401, `{"error": "token_expired"}` |
| `telegram_chat_id` — строка вместо int | 422 |
| Удаление аккаунта с активными watch'ами | Каскадное удаление всех связанных документов до удаления `user` |
| JWT используется после удаления аккаунта | `services/authz` не находит `user` → 401 |
| Смена пароля со старым == новым | Принять (не ошибка); сервис просто перехэширует |
| `new_password` < 8 символов | 422 |

---

## 2. watches

### 2.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| W-1 | Пользователь | Создать watch для маршрута с датами и правилом | Автоматически отслеживать цену |
| W-2 | Пользователь | Задать правило: порог / новый минимум / процент падения / дайджест | Получать алерт в нужный момент |
| W-3 | Пользователь | Видеть список всех watch'ей с текущей ценой | Понимать общую картину маршрутов |
| W-4 | Пользователь | Приостановить watch без потери истории | Временно отключить отслеживание |
| W-5 | Пользователь | Удалить watch вместе с историей | Убрать ненужный маршрут |
| W-6 | Free-пользователь | Получить ошибку при попытке создать 4-й watch | Понимать ограничение плана |
| W-7 | Пользователь | Вручную запустить проверку цены («Check now») | Получить актуальные данные немедленно |
| W-8 | Пользователь | Видеть all-time-low цену и дату | Оценить, хорошее ли сейчас предложение |

### 2.2 Модель данных

**Коллекция: `watches`**

| Поле | Тип | Ограничения | По умолчанию |
|---|---|---|---|
| `_id` | `ObjectId` | PK | авто |
| `user_id` | `ObjectId` | ref: `users` | — |
| `origin` | `str` | 3 символа, A-Z | — |
| `destination` | `str` | 3 символа, A-Z | — |
| `date_mode` | `str` | enum: `"exact"` \| `"range"` | — |
| `depart_date` | `date \| null` | если `date_mode == "exact"` | `null` |
| `return_date` | `date \| null` | опционально, `date_mode == "exact"` | `null` |
| `date_from` | `date \| null` | если `date_mode == "range"` | `null` |
| `date_to` | `date \| null` | если `date_mode == "range"` | `null` |
| `passengers` | `int` | 1–9 | `1` |
| `cabin` | `str` | enum: `"economy"` \| `"business"` \| `"first"` | `"economy"` |
| `rule` | `object` | см. ниже | — |
| `active` | `bool` | — | `true` |
| `lowest_seen` | `float \| null` | EUR | `null` |
| `lowest_seen_at` | `datetime \| null` | UTC | `null` |
| `last_checked_at` | `datetime \| null` | UTC | `null` |
| `last_alerted_at` | `datetime \| null` | UTC | `null` |
| `last_offer` | `object \| null` | см. ниже | `null` |
| `created_at` | `datetime` | UTC | `now()` |
| `updated_at` | `datetime` | UTC | `now()` |

**Вложенный объект `rule`:**

| Поле | Тип | Условие |
|---|---|---|
| `type` | `str` | enum: `"threshold"` \| `"new_low"` \| `"drop_pct"` \| `"digest"` |
| `threshold_price` | `float \| null` | обязателен если `type == "threshold"`; > 0 |
| `drop_pct` | `float \| null` | обязателен если `type == "drop_pct"`; 1.0–99.0 |
| `digest_time` | `str \| null` | обязателен если `type == "digest"`; формат `"HH:MM"` UTC |

**Вложенный объект `last_offer`:**

| Поле | Тип |
|---|---|
| `price` | `float` |
| `airline` | `str` (IATA 2 символа) |
| `airline_name` | `str` |
| `stops` | `int` |
| `depart_at` | `datetime` |
| `arrive_at` | `datetime` |
| `duration_min` | `int` |
| `deep_link` | `str \| null` |

**Индексы:**
- `{user_id: 1}` — список watch'ей пользователя
- `{active: 1}` — fan-out планировщика
- `{user_id: 1, active: 1}` — составной для лимита плана

### 2.3 API

#### POST `/api/v1/watches`
Создаёт новый watch.

**Тело:**
```json
{
  "origin": "RIX",
  "destination": "BCN",
  "date_mode": "exact",
  "depart_date": "2025-09-15",
  "return_date": "2025-09-22",
  "passengers": 1,
  "cabin": "economy",
  "rule": {
    "type": "threshold",
    "threshold_price": 90.00
  }
}
```

**Ответ 201:** полный документ watch (та же схема, что модель данных выше).

| Код | Причина |
|---|---|
| 201 | Создан |
| 400 | Лимит плана достигнут (`"error": "plan_limit_reached", "limit": 3, "current": 3`) |
| 401 | Не аутентифицирован |
| 422 | Валидация (origin==destination, прошедшие даты, недопустимый IATA и т.д.) |

---

#### GET `/api/v1/watches`
Список всех watch'ей пользователя.

**Ответ 200:**
```json
[
  { /* watch document */ },
  { /* watch document */ }
]
```

| Код | Причина |
|---|---|
| 200 | OK (пустой массив если нет) |
| 401 | Не аутентифицирован |

---

#### GET `/api/v1/watches/{watch_id}`
Один watch.

**Ответ 200:** полный документ watch.

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Не аутентифицирован |
| 403 | Watch принадлежит другому пользователю |
| 404 | Не найден |

---

#### PATCH `/api/v1/watches/{watch_id}`
Частичное обновление (правило, active, даты).

**Тело (все поля опциональны):**
```json
{
  "active": false,
  "rule": {
    "type": "new_low"
  }
}
```

**Ответ 200:** обновлённый watch.

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Не аутентифицирован |
| 403 | Чужой watch |
| 404 | Не найден |
| 422 | Попытка изменить `origin`/`destination`; невалидное правило |

---

#### DELETE `/api/v1/watches/{watch_id}`
Удаляет watch и всю связанную историю.

**Ответ:** `204 No Content`

| Код | Причина |
|---|---|
| 204 | Удалено |
| 401 | Не аутентифицирован |
| 403 | Чужой watch |
| 404 | Не найден |

---

#### POST `/api/v1/watches/{watch_id}/check`
Немедленная постановка задачи опроса в очередь.

**Тело:** пусто.

**Ответ 202:**
```json
{ "job_id": "a1b2c3d4-..." }
```

| Код | Причина |
|---|---|
| 202 | Принято, задача поставлена в очередь |
| 401 | Не аутентифицирован |
| 403 | Чужой watch |
| 404 | Не найден |
| 429 | Слишком частые ручные проверки (cooldown 5 мин на watch) |

---

#### GET `/api/v1/watches/{watch_id}/snapshots`
История снэпшотов цен для графика.

**Query-параметры:** `limit` (default 100, max 500), `from_date` (ISO date), `to_date` (ISO date).

**Ответ 200:**
```json
[
  {
    "checked_at": "2025-06-01T06:00:00Z",
    "price": 87.50,
    "airline": "VY",
    "airline_name": "Vueling",
    "stops": 0
  }
]
```

| Код | Причина |
|---|---|
| 200 | OK (пустой массив если нет данных) |
| 401 | Не аутентифицирован |
| 403 | Чужой watch |
| 404 | Не найден |

---

### 2.4 Экраны / Состояния

**Список watch'ей** — карточки (см. [раздел 8](#8-dashboard)).

**Форма создания watch** (`/watches/new`):
- Шаг 1: Маршрут — поля `origin`, `destination` (IATA, заглавные), кнопка «Поменять местами»
- Шаг 2: Даты — переключатель `exact` / `range` → соответствующие date picker'ы
- Шаг 3: Пассажиры (счётчик 1–9) + класс (dropdown: economy / business / first)
- Шаг 4: Правило — radio-кнопки типа → появляются доп. поля (threshold_price, drop_pct, digest_time)
- Submit: кнопка активна только при валидных полях
- После создания: redirect на `/watches/{id}`

**Состояния формы:** `idle` | `submitting` | `error` (inline по полям) | `plan_limit` (баннер вместо формы)

### 2.5 Бизнес-логика

1. **Лимит плана:** перед созданием подсчитать `watches.count({user_id, active: true})`; если ≥ plan_limit → 400.
2. **IATA-валидация:** 3 символа, только A-Z (regex `^[A-Z]{3}$`).
3. **Валидация дат:**
   - `depart_date` ≥ `today + 1 день`
   - `return_date` > `depart_date` если задан
   - `date_from` < `date_to`; `date_to - date_from` ≤ 90 дней
   - `date_from` ≥ `today + 1 день`
4. **Немедленный опрос:** после создания watch немедленно ставить `poll_watch(watch_id)` в очередь (не ждать планировщика).
5. **Неизменяемые поля:** `origin`, `destination` нельзя изменить через PATCH — возврат 422 с `"error": "field_immutable"`.
6. **Пауза (`active=false`):** планировщик пропускает неактивные watch'и; история и lowest_seen сохраняются.
7. **Каскадное удаление watch:**
   - Удалить `price_snapshots` где `watch_id = X`
   - Удалить `alerts` где `watch_id = X`
   - Удалить сам документ `watches`
8. **Cooldown ручной проверки:** Redis ключ `manual_check:{watch_id}` TTL 5 мин; при наличии → 429.

### 2.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| `origin == destination` | 422, `"error": "same_origin_destination"` |
| Дата вылета в прошлом | 422, `"error": "date_in_past"` |
| `date_from > date_to` | 422, `"error": "invalid_date_range"` |
| Диапазон дат > 90 дней | 422, `"error": "date_range_too_wide"` |
| `threshold_price <= 0` | 422 |
| `drop_pct` вне диапазона 1–99 | 422 |
| `digest_time` не в формате `HH:MM` | 422 |
| Дублирующий маршрут+дата у одного пользователя | Разрешено (разные правила) |
| Лимит плана достигнут | 400, `{"error": "plan_limit_reached", "limit": 3, "current": 3}` |
| PATCH чужого watch | 403 |
| Check-now дважды за 5 мин | 429, `{"error": "check_cooldown", "retry_after": 120}` |

---

## 3. provider

### 3.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| P-1 | Система | Запрашивать актуальные цены у Amadeus | Снэпшоты отражали реальные предложения |
| P-2 | Система | Переключаться на MockProvider без изменения логики | Dev/тесты работали без API-ключей |
| P-3 | Система | Получать нормализованный список предложений | rules-engine был независим от источника |
| P-4 | Система | Кэшировать Amadeus OAuth-токен в Redis | Не превышать лимит авторизационных запросов |
| P-5 | Система | Повторять запросы с backoff при сбоях | Временные ошибки сети не теряли задачу |

### 3.2 Модель данных

**Не коллекция MongoDB** — внутренние структуры данных Python.

**`SearchParams` (вход провайдера):**

| Поле | Тип | Описание |
|---|---|---|
| `origin` | `str` | IATA 3 символа |
| `destination` | `str` | IATA 3 символа |
| `depart_date` | `date` | Дата вылета (если range — `date_from`) |
| `return_date` | `date \| None` | Дата возврата |
| `passengers` | `int` | 1–9 |
| `cabin` | `str` | `"economy"` / `"business"` / `"first"` |
| `currency` | `str` | `"EUR"` (hardcoded) |

**`Offer` (нормализованное предложение, выход провайдера):**

| Поле | Тип | Описание |
|---|---|---|
| `price` | `float` | Итоговая цена в EUR |
| `airline` | `str` | IATA-код перевозчика (2 символа) |
| `airline_name` | `str` | Полное название |
| `stops` | `int` | 0 = прямой рейс |
| `depart_at` | `datetime` | UTC |
| `arrive_at` | `datetime` | UTC |
| `duration_min` | `int` | Общая длительность в минутах |
| `deep_link` | `str \| None` | Ссылка на бронирование |
| `raw_id` | `str` | ID предложения у провайдера (для dedup) |

**Redis-кэш Amadeus-токена:**
- Ключ: `amadeus:access_token`
- Значение: `str` (Bearer token)
- TTL: `expires_in - 60` секунд

### 3.3 API (внутренний интерфейс)

HTTP-эндпоинтов нет. Абстрактный интерфейс:

```
FareProvider (abstract)
  search(params: SearchParams) -> list[Offer]
    raises: ProviderTimeout | ProviderError | NoOffersFound

AmadeusProvider(FareProvider)
  _authenticate() -> str   # получает/обновляет токен
  search(params)           # вызывает Amadeus Flight Offers Search v2

MockProvider(FareProvider)
  search(params)           # возвращает детерминированные тестовые данные
```

**Amadeus Flight Offers Search:**
- `GET https://api.amadeus.com/v2/shopping/flight-offers`
- Query: `originLocationCode`, `destinationLocationCode`, `departureDate`, `returnDate?`, `adults`, `travelClass`, `max=10`, `currencyCode=EUR`
- Auth: `Authorization: Bearer <token>`

**Amadeus OAuth2:**
- `POST https://api.amadeus.com/v1/security/oauth2/token`
- Body: `grant_type=client_credentials&client_id=...&client_secret=...`

### 3.4 Экраны / Состояния

Модуль полностью внутренний — UI отсутствует.

Логи провайдера доступны через структурные логи (stdout/stderr) и видны в `docker compose logs worker`.

### 3.5 Бизнес-логика

1. **Выбор провайдера:** определяется конфигом (`FARE_PROVIDER=amadeus|mock`); в тестах всегда `mock`.
2. **AmadeusProvider — аутентификация:**
   - Проверить Redis ключ `amadeus:access_token`
   - Если есть → использовать; если нет → `POST /v1/security/oauth2/token` → сохранить в Redis с TTL
3. **AmadeusProvider — поиск:**
   - Маппинг `cabin`: `economy→ECONOMY`, `business→BUSINESS`, `first→FIRST_CLASS`
   - Выбрать `max=10` предложений; результат отсортировать по `price asc`
   - Нормализовать: из каждого itinerary взять первый и последний сегмент для `depart_at`/`arrive_at`; `stops = len(segments) - 1`
4. **MockProvider:**
   - Базовая цена: `hash(origin+destination) % 100 + 60` EUR (детерминировано по маршруту)
   - Каждый вызов добавляет случайный шум `±15 %` с сидом `(origin+destination+date.isoformat())`
   - Возвращает 3–5 предложений разных «авиакомпаний» (`W6`, `VY`, `FR`)
   - Для `date_mode == "range"`: выбирает случайную дату из диапазона на каждый вызов
5. **Retry-политика:** 3 попытки, backoff 1s → 2s → 4s; при исчерпании пробросить исключение в Celery-задачу
6. **Rate-limiter Amadeus:** Redis счётчик `amadeus:rps` с TTL 1s; при превышении 9 req/s — sleep 100 мс

### 3.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| Amadeus возвращает 0 предложений | Вернуть `[]`; poll-worker запишет снэпшот с `price=null` |
| Amadeus 401 (истёкший токен) | Удалить Redis-ключ, переаутентифицироваться, повторить запрос 1 раз |
| Amadeus 429 (rate limit) | Backoff 5s, затем retry; при трёх подряд → `ProviderError` |
| Таймаут сети (5 с) | Поднять `ProviderTimeout`; Celery повторит задачу |
| Amadeus возвращает цены не в EUR | Запрос всегда содержит `currencyCode=EUR`; если ответ в другой валюте — логировать и пропустить такое предложение |
| MockProvider + `date_mode == "range"` | Случайная дата в диапазоне; сид меняется между вызовами → цена чуть разная |
| Credentials не заданы в `.env` | `AmadeusProvider.__init__` поднимает `ConfigError` при старте; сервис не запускается |

---

## 4. scheduler

### 4.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| S-1 | Система | Активные watch'и проверялись по интервалу плана | Цены всегда были свежими |
| S-2 | Система | Задачи опроса были разнесены во времени | Amadeus не получал шквал запросов одновременно |
| S-3 | Система | Планировщик был идемпотентным | Двойной запуск Beat не дублировал задачи |
| S-4 | Оператор | Видеть статус планировщика через `/health` | Диагностировать зависание Beat |

### 4.2 Модель данных

Собственной коллекции нет. Читает:
- `watches` (`{active: true}`) — для fan-out
- `users` — для получения плана (и расчёта интервала)

**Redis-ключи:**

| Ключ | Тип | TTL | Назначение |
|---|---|---|---|
| `scheduler:lock` | `string` | 300 с | Mutex против двойного fan-out |
| `scheduler:last_run` | `string` | без TTL | Timestamp последнего успешного fan-out |

**Celery Beat schedule (`beat_schedule` dict):**

```python
"fan_out_polls": {
    "task": "workers.tasks.fan_out_polls",
    "schedule": crontab(minute=0),   # каждый час, в :00
}
"send_digests": {
    "task": "workers.tasks.send_digests",
    "schedule": crontab(minute=0),   # каждый час; задача сама фильтрует по digest_time
}
```

### 4.3 API

#### GET `/api/v1/health`
Возвращает статус всех компонентов (доступен без авторизации).

**Ответ 200:**
```json
{
  "status": "ok",
  "mongo": "ok",
  "redis": "ok",
  "scheduler_last_run": "2025-06-01T06:00:00Z",
  "active_watches": 42
}
```

| Код | Причина |
|---|---|
| 200 | Всё в норме |
| 503 | Один или несколько компонентов недоступны |

*(Остальные admin-эндпоинты вынесены за MVP)*

### 4.4 Экраны / Состояния

Отдельного экрана нет.
- Dashboard показывает `last_checked_at` на каждой карточке watch'а.
- Пользователь видит «Последняя проверка: 2 ч назад».

### 4.5 Бизнес-логика

**Задача `fan_out_polls`:**
1. Получить Redis-lock `SET scheduler:lock 1 EX 300 NX`; если lock занят → завершить (идемпотентность).
2. Загрузить все `watches` с `{active: true}` из MongoDB.
3. Для каждого watch:
   - Загрузить `user.plan` через `watch.user_id`
   - `poll_interval = {free: 12h, pro: 3h, team: 1h}[plan]`
   - `next_due = (last_checked_at + poll_interval)` если `last_checked_at` не `null`, иначе `created_at`
   - Если `now >= next_due` → добавить в список `due_watches`
4. Stagger-задержка: `stagger_delay_i = i * (1800 / len(due_watches))` секунд (распределить по 30 мин).
5. Для каждого `watch` из `due_watches`: `poll_watch.apply_async(args=[str(watch._id)], countdown=stagger_delay_i)`.
6. Обновить Redis `scheduler:last_run` = `now.isoformat()`.
7. Освободить lock (ключ истечёт сам по TTL).

**Задача `send_digests`:**
1. Загрузить все `watches` с `{active: true, "rule.type": "digest"}`.
2. Текущий час UTC — `current_hour = now.strftime("%H:%M")` (округлённый до часа: `HH:00`).
3. Отфильтровать watch'и, у которых `rule.digest_time == current_hour`.
4. Для каждого: вызвать `notifier.send_digest(watch)`.

### 4.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| Beat запускается дважды подряд | Redis-lock блокирует второй fan-out; первый завершается нормально |
| Watch удалён между fan-out и poll | `poll_watch` обнаруживает `watch not found` → завершается без ошибки |
| Все watch'и сразу за интервал (первый запуск) | Stagger применяется; не более 1 задачи/1 с |
| Downgrade плана пользователя | Следующий fan-out подберёт новый интервал автоматически |
| MongoDB недоступен во время fan-out | `fan_out_polls` получает ошибку → Celery помечает задачу failed; Beat повторит через час |
| 0 активных watch'ей | Fan-out завершается немедленно, ничего не ставит в очередь |
| `digest_time` в нестандартном часовом поясе | Хранится как UTC HH:MM; документировать в UI |

---

## 5. poll-worker

### 5.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| PW-1 | Система | Получить cheapest offer и сохранить снэпшот | История цен пополнялась |
| PW-2 | Система | Обновлять `lowest_seen` атомарно | Не терять all-time-low при конкурентных вызовах |
| PW-3 | Система | Кэшировать последнюю цену в Redis | Dashboard читал быстро |
| PW-4 | Система | Передавать текущую цену в rules-engine | Алерты срабатывали своевременно |
| PW-5 | Система | Gracefully обрабатывать ошибки провайдера | Один сбой не ломал всё расписание |

### 5.2 Модель данных

**Коллекция: `price_snapshots`** (time-series)

Создаётся с опциями:
```python
db.create_collection("price_snapshots", timeseries={
    "timeField": "checked_at",
    "metaField": "watch_id",
    "granularity": "hours"
})
```

| Поле | Тип | Описание |
|---|---|---|
| `watch_id` | `ObjectId` | MetaField; ref: `watches` |
| `checked_at` | `datetime` | TimeField; UTC |
| `price` | `float \| null` | EUR; `null` если предложений не найдено |
| `airline` | `str \| null` | IATA 2 символа |
| `airline_name` | `str \| null` | Полное название |
| `stops` | `int \| null` | — |
| `depart_at` | `datetime \| null` | UTC |
| `arrive_at` | `datetime \| null` | UTC |
| `duration_min` | `int \| null` | — |
| `deep_link` | `str \| null` | — |
| `provider` | `str` | `"amadeus"` / `"mock"` |

**Индексы:** встроенный time-series индекс по `{watch_id, checked_at}`.

**Redis-ключи:**

| Ключ | Тип | TTL | Описание |
|---|---|---|---|
| `lastprice:{watch_id}` | `hash` | `poll_interval + 30 мин` | `price`, `airline`, `checked_at` — быстрое чтение |

### 5.3 API (внутренний)

Celery-задача (не HTTP):
```
poll_watch(watch_id: str)
  bind=True, max_retries=3, default_retry_delay=60
  autoretry_for=(ProviderTimeout, ProviderError)
  retry_backoff=True
```

### 5.4 Экраны / Состояния

Нет (фоновая задача). Косвенно влияет на:
- Обновление `last_checked_at` на карточке watch'а в дашборде
- Пополнение графика истории цен

### 5.5 Бизнес-логика

**Алгоритм `poll_watch(watch_id)`:**

1. Загрузить `watch = watches.find_one({_id: watch_id})`.
   - Если `watch is None` или `watch.active == false` → завершить без ошибки.
2. Загрузить `user = users.find_one({_id: watch.user_id})`.
3. Выбрать провайдера: `provider = AmadeusProvider()` или `MockProvider()` по конфигу.
4. Построить `SearchParams` из полей watch:
   - `date_mode == "exact"` → `depart_date = watch.depart_date`
   - `date_mode == "range"` → `depart_date = watch.date_from` (провайдер может получать оба варианта)
5. `offers = provider.search(params)`.
6. **Если `offers` пустой список:**
   - Записать снэпшот с `price=null`, `provider=...`
   - Обновить `watches.last_checked_at = now`
   - Завершить (rules-engine не вызывать)
7. Взять `best = offers[0]` (уже отсортированы по цене asc).
8. Записать документ в `price_snapshots`.
9. Обновить `watches` атомарно:
   ```python
   watches.update_one(
       {"_id": watch_id},
       {
           "$set": {
               "last_checked_at": now,
               "last_offer": {price, airline, ...},
               "updated_at": now
           },
           "$min": {"lowest_seen": best.price},   # атомарный минимум
           "$set": {"lowest_seen_at": now}         # обновлять только если $min изменил
       }
   )
   ```
   *(Использовать `$min` для атомарного обновления `lowest_seen`.)*
   *(Если `lowest_seen_at` нужно обновлять только при новом минимуме — сравнить до/после через агрегацию или два запроса.)*
10. Записать в Redis: `HSET lastprice:{watch_id} price {best.price} airline {best.airline} checked_at {now.isoformat()}` + `EXPIRE`.
11. Вызвать `rules_engine.evaluate(watch=watch, current_price=best.price, old_lowest=watch.lowest_seen)`.

**Retry:** Celery `autoretry_for=(ProviderTimeout, ProviderError)`, max 3 попытки, exponential backoff.

### 5.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| `active` watch переключён в `false` между постановкой в очередь и выполнением | Шаг 1: обнаружить `active=false` → завершить |
| Provider timeout | Celery retry (до 3x) → затем task failed, логировать |
| Конкурентные `poll_watch` для одного `watch_id` (manual + scheduled) | Последняя запись побеждает; оба снэпшота сохраняются (допустимо) |
| `$min` обновляет `lowest_seen` и `lowest_seen_at` одновременно | Обновлять `lowest_seen_at` только если новое значение `lowest_seen` меньше предыдущего — проверить через `findOneAndUpdate` с `returnDocument=BEFORE` |
| MongoDB недоступна при записи снэпшота | Celery retry; логировать |
| `price_snapshots` time-series не принимает запись (неправильная схема) | `ProviderError` → retry → task failed; alert в логах |

---

## 6. rules-engine

### 6.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| R-1 | Пользователь | Получать алерт, когда цена ≤ моего порога | Поймать хорошую цену |
| R-2 | Пользователь | Получать алерт при новом историческом минимуме | Знать, что дешевле ещё не было |
| R-3 | Пользователь | Получать алерт при падении цены на X% | Реагировать на резкие скидки |
| R-4 | Пользователь | Получать ежедневный дайджест в заданное время | Видеть сводку без лишних алертов |
| R-5 | Система | Не слать повторные алерты в окне кулдауна | Не раздражать пользователя |

### 6.2 Модель данных

Собственной коллекции нет.

**Redis-ключи кулдауна:**

| Ключ | TTL | Правило |
|---|---|---|
| `cooldown:{watch_id}:threshold` | 24 ч | threshold |
| `cooldown:{watch_id}:new_low` | 12 ч | new_low |
| `cooldown:{watch_id}:drop_pct` | 12 ч | drop_pct |
| `cooldown:{watch_id}:digest` | 20 ч | digest (через отдельную задачу) |

Читает из MongoDB:
- `watches.rule`, `watches.lowest_seen` — текущий контекст
- `price_snapshots` — предыдущий снэпшот (для `drop_pct`)

### 6.3 API (внутренний)

```
rules_engine.evaluate(
    watch: Watch,
    current_price: float,
    old_lowest: float | None
) -> bool
    # Возвращает True если алерт был отправлен

rules_engine.evaluate_digest(watch: Watch) -> None
    # Вызывается scheduler'ом; формирует и отправляет дайджест
```

### 6.4 Экраны / Состояния

Нет UI. Результат правила виден косвенно:
- Значок «Сработало» в строке лога алертов на дашборде
- Badge на карточке watch'а (последний алерт N часов назад)

### 6.5 Бизнес-логика

**`evaluate(watch, current_price, old_lowest)`:**

```
rule = watch.rule

if rule.type == "threshold":
    fired = current_price <= rule.threshold_price

elif rule.type == "new_low":
    # old_lowest передан poll-worker'ом ДО обновления watches.lowest_seen
    fired = (old_lowest is None) or (current_price < old_lowest)

elif rule.type == "drop_pct":
    prev = price_snapshots.find_one(
        {watch_id: watch._id, price: {$ne: null}},
        sort={checked_at: -1},
        skip=1          # пропустить только что записанный текущий снэпшот
    )
    if prev and prev.price:
        drop = (prev.price - current_price) / prev.price * 100
        fired = drop >= rule.drop_pct
    else:
        fired = False

elif rule.type == "digest":
    fired = False       # управляется задачей send_digests

if fired:
    key = f"cooldown:{watch._id}:{rule.type}"
    if redis.exists(key):
        return False    # в кулдауне — подавить
    redis.set(key, "1", ex=COOLDOWN[rule.type])
    notifier.send_alert(
        watch=watch,
        user=user,
        price=current_price,
        rule_type=rule.type
    )
    return True

return False
```

**`evaluate_digest(watch)`:**
1. Сформировать сводку: `watch.last_offer.price`, `watch.lowest_seen`, `watch.last_checked_at`
2. Проверить cooldown `cooldown:{watch_id}:digest`; если занят — пропустить
3. Поставить cooldown 20 ч
4. Вызвать `notifier.send_digest(watch, user)`

**Константы кулдауна:**
```python
COOLDOWN = {
    "threshold": 86400,   # 24 ч
    "new_low":   43200,   # 12 ч
    "drop_pct":  43200,   # 12 ч
    "digest":    72000,   # 20 ч
}
```

### 6.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| `current_price` is `None` | `evaluate` не вызывается (poll-worker пропускает) |
| `new_low` на первом снэпшоте (`old_lowest is None`) | `fired = True` — первая известная цена = минимум |
| `drop_pct` и только один снэпшот (prev is None) | `fired = False` |
| `drop_pct` и предыдущий снэпшот с `price=null` | `fired = False` |
| Кулдаун истёк, цена всё ещё низкая | Алерт срабатывает повторно — корректное поведение |
| Правило изменено пока кулдаун активен | Кулдаун остаётся, новые параметры применяются на следующем evaluate после его истечения |
| Два конкурентных `evaluate` для одного watch | Redis `SET NX` кулдауна — атомарная операция; только один сможет выставить ключ → один алерт |
| Digest и пустой `last_offer` | Дайджест отправляется с пометкой «нет актуальных данных» вместо цены |

---

## 7. notifier

### 7.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| N-1 | Пользователь | Получать Telegram-сообщение при срабатывании правила | Сразу видеть алерт в мессенджере |
| N-2 | Pro-пользователь | Получать алерт также на email | Иметь резервный канал |
| N-3 | Пользователь | Получать дайджест раз в день | Сводка без лишних уведомлений |
| N-4 | Система | Логировать каждую попытку отправки | Видеть историю и ошибки доставки |
| N-5 | Пользователь | Видеть лог алертов в дашборде | Знать, когда и почему сработало |

### 7.2 Модель данных

**Коллекция: `alerts`**

| Поле | Тип | Описание |
|---|---|---|
| `_id` | `ObjectId` | PK |
| `watch_id` | `ObjectId` | ref: `watches` |
| `user_id` | `ObjectId` | ref: `users` (денормализовано для быстрого фильтра) |
| `rule_type` | `str` | `"threshold"` \| `"new_low"` \| `"drop_pct"` \| `"digest"` |
| `triggered_at` | `datetime` | UTC |
| `price` | `float \| null` | Текущая цена при срабатывании |
| `offer` | `object \| null` | Снэпшот предложения (airline, stops, depart_at, duration_min, deep_link) |
| `channel` | `str` | `"telegram"` \| `"email"` \| `"both"` |
| `status` | `str` | `"sent"` \| `"failed"` \| `"partial"` |
| `error` | `str \| null` | Описание ошибки |
| `created_at` | `datetime` | UTC |

**Индексы:**
- `{watch_id: 1, triggered_at: -1}` — лог алертов для watch
- `{user_id: 1, triggered_at: -1}` — лог алертов для пользователя

### 7.3 API

#### GET `/api/v1/alerts`
Список алертов пользователя.

**Query-параметры:** `watch_id` (опционально), `limit`, `offset`.

**Ответ 200:**
```json
[
  {
    "alert_id": "...",
    "watch_id": "...",
    "rule_type": "threshold",
    "triggered_at": "2025-06-01T08:30:00Z",
    "price": 85.00,
    "offer": {
      "airline": "VY",
      "airline_name": "Vueling",
      "stops": 0,
      "depart_at": "2025-09-15T06:00:00Z",
      "duration_min": 195,
      "deep_link": "https://..."
    },
    "channel": "telegram",
    "status": "sent",
    "error": null
  }
]
```

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Не аутентифицирован |

---

#### GET `/api/v1/alerts/{alert_id}`
Один алерт.

| Код | Причина |
|---|---|
| 200 | OK |
| 401 | Не аутентифицирован |
| 403 | Чужой алерт |
| 404 | Не найден |

---

### 7.4 Экраны / Состояния

*(Описание UI — в разделе 8 Dashboard)*

- Таблица алертов: колонки `Время` · `Правило` · `Цена` · `Канал` · `Статус`
- Статус-иконки: ✓ sent / ⚠ partial / ✗ failed
- При клике на строку: развернуть детали предложения

### 7.5 Бизнес-логика

**`notifier.send_alert(watch, user, price, rule_type)`:**

1. Определить каналы:
   - `telegram_ok = user.telegram_chat_id is not None`
   - `email_ok = user.plan in ["pro", "team"] and user.email is not None`
   - Если оба `False` → создать `alert` со `status="failed"`, `error="no_channel"` → завершить
2. Создать `alert` документ со `status="pending"`.
3. Сформировать сообщение (см. шаблоны ниже).
4. Если `telegram_ok` → отправить через Telegram Bot API `sendMessage`; записать результат.
5. Если `email_ok` → отправить через SMTP; записать результат.
6. Определить итоговый `status`:
   - Все успешны → `"sent"`
   - Хоть один успешен → `"partial"`
   - Все провалены → `"failed"`
7. Обновить `alert.status`, `alert.error`; обновить `watch.last_alerted_at`.

**Шаблон Telegram (MarkdownV2):**
```
✈ *FareWatch Alert*

Маршрут: `{origin}` → `{destination}`
Дата: {depart_date}
Цена: *€{price:.0f}* _{rule_description}_
Авиакомпания: {airline_name} · {stops_text} · {duration}

[Забронировать]({deep_link}) | [Открыть в FareWatch]({dashboard_url}/watches/{watch_id})
```

`rule_description` по типу:
- `threshold` → `(ниже порога €{threshold_price:.0f})`
- `new_low` → `(новый исторический минимум!)`
- `drop_pct` → `(падение на {drop_pct:.0f}%)`

**Шаблон дайджеста (Telegram):**
```
📋 *FareWatch — дайджест*

{для каждого watch}
• `{origin}` → `{destination}` ({depart_date})
  Сейчас: €{last_price:.0f} | Минимум: €{lowest_seen:.0f} ({lowest_seen_ago})
```

**Email:** HTML-эквивалент Telegram-шаблона через Jinja2-шаблон; отправляется через SMTP (Mailgun/SendGrid).

### 7.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| Нет ни Telegram, ни email | Alert записан со `status="failed"`, `error="no_channel"` |
| Telegram 403 (пользователь заблокировал бота) | Telegram-канал помечен failed; email отправлен если доступен |
| SMTP-сервер недоступен | Email-канал failed; telegram отправлен если доступен |
| `deep_link` is None | Ссылка «Забронировать» не включается в сообщение |
| Дайджест при `last_offer is None` (ещё не было проверок) | Строка watch: «нет данных» |
| Дайджест без активных digest-watch'ей | Задача не отправляет сообщений |
| Alert для удалённого watch (watch_id стал stale) | Если `watch not found` при формировании сообщения — skip; alert не записывается |
| `price` in alert отличается от `watch.lowest_seen` | Допустимо: alert фиксирует цену в момент срабатывания |

---

## 8. dashboard

### 8.1 User Stories

| ID | Роль | Хочу | Чтобы |
|---|---|---|---|
| D-1 | Пользователь | Видеть список всех watch'ей с текущей ценой | Контролировать все маршруты разом |
| D-2 | Пользователь | Видеть график истории цен для watch'а | Решить: брать сейчас или ждать |
| D-3 | Пользователь | Видеть лучшее текущее предложение (авиакомпания, пересадки, время) | Оценить качество варианта |
| D-4 | Пользователь | Видеть лог алертов для watch'а | Понимать историю срабатываний |
| D-5 | Пользователь | Создавать, паузить, удалять watch'и прямо в UI | Не ходить в API вручную |
| D-6 | Пользователь | Подключить Telegram из настроек | Не искать бота самостоятельно |
| D-7 | Free-пользователь | Видеть баннер о лимите плана | Понимать ограничение и возможность апгрейда |

### 8.2 Модель данных (Frontend state)

**AuthState:**
```typescript
interface AuthState {
  userId: string | null;
  email: string | null;
  plan: "free" | "pro" | "team" | null;
  token: string | null;              // localStorage
  telegramConnected: boolean;
}
```

**WatchListState:**
```typescript
interface WatchListState {
  watches: Watch[];
  loading: boolean;
  error: string | null;
}
```

**WatchDetailState:**
```typescript
interface WatchDetailState {
  watch: Watch | null;
  snapshots: Snapshot[];
  alerts: Alert[];
  loading: boolean;
  chartRange: "7d" | "30d" | "all";
}
```

**Derived ChartData:**
```typescript
type ChartPoint = { x: string; y: number | null };  // x = ISO datetime, y = price
```

### 8.3 API (потребляемые Frontend-ом)

Все эндпоинты из модулей `auth`, `watches`, `notifier` выше, плюс GET `/api/v1/watches/{id}/snapshots`.

Заголовок на каждый запрос: `Authorization: Bearer <token>` (из localStorage).

### 8.4 Экраны / Состояния

---

#### Экран «Вход / Регистрация»

**`/login`** и **`/register`**

| Состояние | Описание |
|---|---|
| `idle` | Пустая форма |
| `loading` | Кнопка disabled, спиннер |
| `error` | Inline-сообщение под полем или над формой |
| `success` | Redirect → `/watches` |

Ссылки: `/login` → `/register` и обратно.

---

#### Экран «Список watch'ей»

**`/watches`**

**Состояния экрана:**
- `loading` — скелетон-карточки
- `empty` — иллюстрация + текст «Нет watch'ей. Создайте первый.» + кнопка
- `plan_limit` — баннер «Достигнут лимит (3/3). Перейдите на Pro.» (кнопка disabled)
- `populated` — сетка карточек

**Карточка watch:**

| Элемент | Данные |
|---|---|
| Маршрут | `origin → destination` (bold) |
| Даты | `depart_date` / `date_from–date_to` |
| Текущая цена | `last_offer.price` в badge (зелёный если < `lowest_seen * 1.05`) |
| Последняя проверка | `last_checked_at` → «2 ч назад» |
| Правило | badge: `< €90` / `Новый минимум` / `–15%` / `Дайджест 08:00` |
| Статус | pill: Активен / Пауза |
| Действия | ▶/⏸ (pause/resume), 🔄 (check now), 🗑 (delete) |

---

#### Экран «Создание watch»

**`/watches/new`**

Пошаговая форма (или single-page с секциями):

1. **Маршрут:** поле `origin` (placeholder `RIX`) · кнопка «⇄» · поле `destination` (placeholder `BCN`)
2. **Даты:** toggle `Конкретные даты / Диапазон` → соответствующие date picker'ы
3. **Пассажиры и класс:** счётчик `[–] 1 [+]` · dropdown `Economy / Business / First`
4. **Правило:**

| Тип | Доп. поле |
|---|---|
| `threshold` | Порог цены (€) — число |
| `new_low` | Нет |
| `drop_pct` | Процент падения (%) |
| `digest` | Время UTC (HH:MM) |

Кнопка «Создать» активна только при валидной форме.

**Состояния:** `idle` | `submitting` | `error` (inline) | `plan_limit_reached` (форма заблокирована + баннер)

---

#### Экран «Детали watch»

**`/watches/{id}`**

**Секции:**

1. **Заголовок:** маршрут, даты, правило, кнопки «Пауза» / «Удалить»
2. **Текущее предложение** (карточка):
   - Цена (большой шрифт) · авиакомпания · пересадки · время вылета/прилёта · длительность
   - Кнопка «Забронировать» (deep_link если есть)
3. **All-time low:** цена + дата
4. **График истории цен** (Recharts `LineChart`):
   - X-ось: datetime; Y-ось: цена EUR
   - Горизонтальная линия: `threshold_price` (если тип `threshold`)
   - Горизонтальная линия: `lowest_seen` (другой цвет)
   - Пробелы при `price=null`
   - Переключатель: `7d | 30d | Всё`
   - Tooltip: дата/время + цена + авиакомпания
5. **Лог алертов** (таблица): `Время` · `Тип` · `Цена` · `Канал` · `Статус`

**Состояния графика:**
- `loading` — placeholder
- `empty` — «Нет данных. Первая проверка ещё не завершена.»
- `no_offers` — «Предложений не найдено. Попробуйте изменить даты.»
- `populated` — полноценный график

---

#### Экран «Настройки»

**`/settings`**

| Секция | Элементы |
|---|---|
| Профиль | email (readonly), план (badge: Free / Pro / Team) |
| Telegram | Статус + инструкция подключения (см. [1.4](#14-экраны--состояния)) |
| Смена пароля | Три поля, кнопка Save |
| Danger zone | Кнопка «Удалить аккаунт» → confirm-диалог |

---

### 8.5 Бизнес-логика

1. **JWT хранится в localStorage**; инъектируется через Axios-interceptor.
2. **401 от любого эндпоинта:** очистить token, redirect на `/login`.
3. **«Check now»:**
   - POST `/watches/{id}/check` → `202`
   - Показать спиннер на карточке
   - Через 10 с сделать GET `/watches/{id}` для обновления `last_checked_at`
   - 429 → toast «Проверка уже запущена, подождите»
4. **Пауза/Резюм:** PATCH `{active: !current}` → оптимистичное обновление UI.
5. **Удаление watch:**
   - Confirm-диалог «Удалить watch и всю историю?»
   - DELETE → убрать из списка
6. **График:**
   - Данные из GET `/watches/{id}/snapshots?limit=100&from_date=...`
   - Сортировка по `checked_at asc` на frontend'е
   - `null`-значения → разрывы линии (`connectNulls=false`)
7. **Относительное время** («2 ч назад»): `formatDistanceToNow` из `date-fns` (locale ru).
8. **Лимит плана:** читать `plan` из `/auth/me`; если `watches.length >= plan_limit` → disable «New Watch», показать баннер.

### 8.6 Крайние случаи

| Ситуация | Поведение |
|---|---|
| Все снэпшоты имеют `price=null` | График: «Предложения для этих дат/маршрута не найдены» |
| История пуста (watch только создан) | График: «Нет данных. Первая проверка ещё не завершена.» |
| Watch удалён из другой сессии | GET `/watches/{id}` → 404 → redirect `/watches`, toast «Watch был удалён» |
| График с единственной точкой | Показать точку (dot), без линии |
| `deep_link` отсутствует | Кнопка «Забронировать» скрыта |
| `last_checked_at` is null (ещё не проверялся) | «Ещё не проверялся» вместо относительного времени |
| Сеть офлайн | Toast «Нет соединения», кнопка Retry |
| Token истёк во время работы | 401 перехватывается → redirect `/login` с query `?session=expired` |
| Plan_limit banner при equal watches/limit | Баннер появляется при `count >= limit`; кнопка «New Watch» disabled |

---

*Конец спецификации FareWatch v1.0*
