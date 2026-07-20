"""
Telegram bot poller — replies to /start with the sender's numeric Chat ID.

Runs as its own long-lived process (see the `bot` service in compose.yml),
separate from the Celery worker pool since it holds a long-polling HTTP
connection open to Telegram rather than picking up queued tasks.
"""
import logging
import time

import httpx
import redis

from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_OFFSET_KEY = "telegram:bot:last_update_id"
_POLL_TIMEOUT = 30


def _get_offset(r: redis.Redis) -> int:
    val = r.get(_OFFSET_KEY)
    return int(val) + 1 if val else 0


def _reply(client: httpx.Client, base_url: str, chat_id: int) -> None:
    text = (
        f"Your Chat ID: {chat_id}\n\n"
        "Paste it into FareWatch: Settings -> Telegram Notifications -> "
        "Chat ID -> Save."
    )
    client.post(f"{base_url}/sendMessage", json={"chat_id": chat_id, "text": text})


def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set — exiting")
        return

    base_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
    r = redis.from_url(settings.REDIS_URL, decode_responses=True)
    client = httpx.Client(timeout=_POLL_TIMEOUT + 10)

    logger.info("Telegram bot poller started")
    while True:
        try:
            resp = client.get(f"{base_url}/getUpdates", params={
                "offset": _get_offset(r),
                "timeout": _POLL_TIMEOUT,
                "allowed_updates": ["message"],
            })
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("getUpdates failed: %s", exc)
            time.sleep(5)
            continue

        for update in data.get("result", []):
            r.set(_OFFSET_KEY, update["update_id"])
            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            chat_id = (message.get("chat") or {}).get("id")
            if chat_id is not None and text.startswith("/start"):
                logger.info("Replying with chat_id=%s", chat_id)
                try:
                    _reply(client, base_url, chat_id)
                except httpx.HTTPError as exc:
                    logger.warning("sendMessage failed: %s", exc)


if __name__ == "__main__":
    main()
