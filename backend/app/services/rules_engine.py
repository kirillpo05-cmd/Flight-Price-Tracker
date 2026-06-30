import logging

logger = logging.getLogger(__name__)

# Full implementation — SPEC.md §6.
# Stubs below allow tasks.py / send_digests to import without error.
# Replace each function body when implementing §6.


def evaluate(watch: dict, current_price: float, old_lowest: float | None) -> bool:
    """Evaluate rule for watch and fire alert if conditions met. Returns True if alert sent."""
    # §6 implementation goes here
    logger.warning("rules_engine.evaluate: not yet implemented (§6)")
    return False


def evaluate_digest(watch: dict) -> None:
    """Build and send digest alert for a digest-rule watch."""
    # §6 implementation goes here
    logger.warning("rules_engine.evaluate_digest: not yet implemented (§6)")
