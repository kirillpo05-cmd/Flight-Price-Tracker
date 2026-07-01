"""
Notifier — SPEC.md §7.
Sends alerts and digests via Telegram Bot API and SMTP.
Runs in Celery sync context; writes to the `alerts` MongoDB collection.
"""
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from bson import ObjectId

from app.core.config import settings
from app.core.db import get_sync_db

logger = logging.getLogger(__name__)

# MarkdownV2 characters that must be escaped in plain/bold/italic content
_MD_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def _escape_md(text: str) -> str:
    """Escape a string for use in Telegram MarkdownV2 text/bold/italic contexts."""
    return "".join(f"\\{c}" if c in _MD_SPECIAL else c for c in str(text))


def _stops_text(stops: int | None) -> str:
    if stops is None:
        return ""
    if stops == 0:
        return "прямой"
    if stops == 1:
        return "1 пересадка"
    if 2 <= stops <= 4:
        return f"{stops} пересадки"
    return f"{stops} пересадок"


def _duration_text(minutes: int | None) -> str:
    if not minutes:
        return ""
    h, m = divmod(minutes, 60)
    return f"{h}ч {m}м" if m else f"{h}ч"


def _rule_description(watch: dict, rule_type: str) -> str:
    rule = watch.get("rule", {})
    if rule_type == "threshold":
        return f"ниже порога €{rule.get('threshold_price', 0):.0f}"
    if rule_type == "new_low":
        return "новый исторический минимум!"
    if rule_type == "drop_pct":
        return f"падение на {rule.get('drop_pct', 0):.0f}%"
    return rule_type


def _build_telegram_alert(watch: dict, price: float, rule_type: str) -> str:
    origin = watch.get("origin", "")
    destination = watch.get("destination", "")
    depart_date = _escape_md(watch.get("depart_date") or watch.get("date_from") or "")
    rule_desc = _escape_md(_rule_description(watch, rule_type))

    offer = watch.get("last_offer") or {}
    airline_name = _escape_md(offer.get("airline_name") or offer.get("airline") or "—")
    stops = _escape_md(_stops_text(offer.get("stops")))
    duration = _escape_md(_duration_text(offer.get("duration_min")))
    deep_link = offer.get("deep_link")

    watch_url = _escape_md(f"{settings.DASHBOARD_URL}/watches/{watch['_id']}")

    lines = [
        "✈ *FareWatch Alert*",
        "",
        f"Маршрут: `{origin}` → `{destination}`",
        f"Дата: {depart_date}",
        f"Цена: *€{price:.0f}* _{rule_desc}_",
        f"Авиакомпания: {airline_name} · {stops} · {duration}",
        "",
    ]

    link_parts = []
    if deep_link:
        link_parts.append(f"[Забронировать]({deep_link})")
    link_parts.append(f"[Открыть в FareWatch]({watch_url})")
    lines.append(" \\| ".join(link_parts))

    return "\n".join(lines)


def _build_telegram_digest(watch: dict) -> str:
    origin = watch.get("origin", "")
    destination = watch.get("destination", "")
    depart_date = _escape_md(watch.get("depart_date") or watch.get("date_from") or "")

    offer = watch.get("last_offer") or {}
    last_price = offer.get("price")
    lowest_seen = watch.get("lowest_seen")

    price_str = _escape_md(f"€{last_price:.0f}") if last_price is not None else "нет данных"
    low_str = _escape_md(f"€{lowest_seen:.0f}") if lowest_seen is not None else "нет данных"

    return "\n".join([
        "📋 *FareWatch — дайджест*",
        "",
        f"• `{origin}` → `{destination}` \\({depart_date}\\)",
        f"  Сейчас: {price_str} \\| Минимум: {low_str}",
    ])


def _send_via_telegram(chat_id: int, text: str) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        })
    if not resp.is_success:
        raise ValueError(f"Telegram {resp.status_code}: {resp.text[:200]}")


def _send_via_email(to_email: str, subject: str, html_body: str) -> None:
    host = settings.SMTP_HOST
    if not host:
        raise ValueError("SMTP_HOST not configured")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_USER or "farewatch@noreply"
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(host, settings.SMTP_PORT, timeout=10) as s:
        s.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        s.sendmail(msg["From"], to_email, msg.as_string())


def _build_email_alert(watch: dict, price: float, rule_type: str) -> tuple[str, str]:
    """Returns (subject, html_body)."""
    origin = watch.get("origin", "")
    destination = watch.get("destination", "")
    rule_desc = _rule_description(watch, rule_type)
    offer = watch.get("last_offer") or {}
    deep_link = offer.get("deep_link", "")
    watch_url = f"{settings.DASHBOARD_URL}/watches/{watch['_id']}"

    subject = f"FareWatch: {origin}→{destination} €{price:.0f} — {rule_desc}"
    html = (
        f"<h2>✈ FareWatch Alert</h2>"
        f"<p><b>Маршрут:</b> {origin} → {destination}<br>"
        f"<b>Цена:</b> €{price:.0f} <em>({rule_desc})</em><br>"
        f"<b>Авиакомпания:</b> {offer.get('airline_name') or offer.get('airline') or '—'}<br>"
        f"<b>Пересадки:</b> {_stops_text(offer.get('stops'))}<br>"
        f"<b>Длительность:</b> {_duration_text(offer.get('duration_min'))}</p>"
        f"{'<p><a href=\"' + deep_link + '\">Забронировать</a></p>' if deep_link else ''}"
        f"<p><a href=\"{watch_url}\">Открыть в FareWatch</a></p>"
    )
    return subject, html


def _build_email_digest(watch: dict) -> tuple[str, str]:
    origin = watch.get("origin", "")
    destination = watch.get("destination", "")
    offer = watch.get("last_offer") or {}
    price = offer.get("price")
    lowest = watch.get("lowest_seen")

    subject = f"FareWatch дайджест: {origin}→{destination}"
    price_str = f"€{price:.0f}" if price is not None else "нет данных"
    low_str = f"€{lowest:.0f}" if lowest is not None else "нет данных"
    html = (
        f"<h2>📋 FareWatch — дайджест</h2>"
        f"<p><b>{origin} → {destination}</b><br>"
        f"Сейчас: {price_str} | Минимум: {low_str}</p>"
        f"<p><a href=\"{settings.DASHBOARD_URL}/watches/{watch['_id']}\">Открыть в FareWatch</a></p>"
    )
    return subject, html


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _resolve_channels(user: dict) -> tuple[bool, bool]:
    tg = user.get("telegram_chat_id") is not None
    em = user.get("plan") in ("pro", "team") and bool(user.get("email"))
    return tg, em


def _channel_label(tg: bool, em: bool) -> str:
    if tg and em:
        return "both"
    return "telegram" if tg else "email"


def _dispatch(
    db,
    alert_id: ObjectId,
    watch: dict,
    user: dict,
    tg_ok: bool,
    em_ok: bool,
    tg_text: str,
    email_subject: str,
    email_html: str,
) -> None:
    """Send over enabled channels, update alert status."""
    tg_sent = em_sent = False
    errors: list[str] = []

    if tg_ok:
        try:
            _send_via_telegram(user["telegram_chat_id"], tg_text)
            tg_sent = True
            logger.info("notifier: Telegram sent alert_id=%s", alert_id)
        except Exception as exc:
            logger.warning("notifier: Telegram failed alert_id=%s: %s", alert_id, exc)
            errors.append(f"telegram: {exc}")

    if em_ok:
        try:
            _send_via_email(user["email"], email_subject, email_html)
            em_sent = True
            logger.info("notifier: email sent alert_id=%s", alert_id)
        except Exception as exc:
            logger.warning("notifier: email failed alert_id=%s: %s", alert_id, exc)
            errors.append(f"email: {exc}")

    successes = sum([tg_sent and tg_ok, em_sent and em_ok])
    attempts = sum([tg_ok, em_ok])
    if successes == attempts:
        status = "sent"
    elif successes > 0:
        status = "partial"
    else:
        status = "failed"

    db.alerts.update_one(
        {"_id": alert_id},
        {"$set": {"status": status, "error": "; ".join(errors) or None}},
    )
    logger.info("notifier: dispatch done alert_id=%s status=%s", alert_id, status)


def send_alert(watch: dict, user: dict, price: float, rule_type: str) -> None:
    """Insert alert doc, send Telegram/email, update status and last_alerted_at."""
    tg_ok, em_ok = _resolve_channels(user)
    now = datetime.now(timezone.utc)
    db = get_sync_db()

    if not tg_ok and not em_ok:
        db.alerts.insert_one({
            "watch_id": watch["_id"],
            "user_id": user["_id"],
            "rule_type": rule_type,
            "triggered_at": now,
            "price": price,
            "offer": watch.get("last_offer"),
            "channel": "none",
            "status": "failed",
            "error": "no_channel",
            "created_at": now,
        })
        logger.warning(
            "notifier: no channel watch=%s user=%s", watch["_id"], user["_id"]
        )
        return

    alert_id = ObjectId()
    db.alerts.insert_one({
        "_id": alert_id,
        "watch_id": watch["_id"],
        "user_id": user["_id"],
        "rule_type": rule_type,
        "triggered_at": now,
        "price": price,
        "offer": watch.get("last_offer"),
        "channel": _channel_label(tg_ok, em_ok),
        "status": "pending",
        "error": None,
        "created_at": now,
    })

    tg_text = _build_telegram_alert(watch, price, rule_type)
    email_subject, email_html = _build_email_alert(watch, price, rule_type)

    _dispatch(db, alert_id, watch, user, tg_ok, em_ok, tg_text, email_subject, email_html)

    db.watches.update_one(
        {"_id": watch["_id"]},
        {"$set": {"last_alerted_at": now, "updated_at": now}},
    )


def send_digest(watch: dict, user: dict) -> None:
    """Insert digest alert doc, send Telegram/email, update status."""
    tg_ok, em_ok = _resolve_channels(user)
    now = datetime.now(timezone.utc)
    db = get_sync_db()

    if not tg_ok and not em_ok:
        logger.warning("notifier: no channel for digest watch=%s", watch["_id"])
        return

    offer = watch.get("last_offer") or {}
    alert_id = ObjectId()
    db.alerts.insert_one({
        "_id": alert_id,
        "watch_id": watch["_id"],
        "user_id": user["_id"],
        "rule_type": "digest",
        "triggered_at": now,
        "price": offer.get("price"),
        "offer": watch.get("last_offer"),
        "channel": _channel_label(tg_ok, em_ok),
        "status": "pending",
        "error": None,
        "created_at": now,
    })

    tg_text = _build_telegram_digest(watch)
    email_subject, email_html = _build_email_digest(watch)

    _dispatch(db, alert_id, watch, user, tg_ok, em_ok, tg_text, email_subject, email_html)
