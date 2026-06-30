import logging

logger = logging.getLogger(__name__)

# Full implementation — SPEC.md §7.
# Stubs below allow rules_engine (§6) to import without error.
# Replace each function body when implementing §7.


def send_alert(watch: dict, user: dict, price: float, rule_type: str) -> None:
    """Send alert via Telegram and/or email depending on user plan."""
    # §7 implementation goes here
    logger.warning(
        "notifier.send_alert: not yet implemented (§7) — watch=%s rule=%s price=%.2f",
        watch.get("_id"),
        rule_type,
        price,
    )


def send_digest(watch: dict, user: dict) -> None:
    """Send daily digest message for a digest-rule watch."""
    # §7 implementation goes here
    logger.warning(
        "notifier.send_digest: not yet implemented (§7) — watch=%s",
        watch.get("_id"),
    )
