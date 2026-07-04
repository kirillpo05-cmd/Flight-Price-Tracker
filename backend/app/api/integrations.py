from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/telegram")
async def telegram_info() -> dict:
    """Returns bot connection details for the Settings page."""
    username = settings.TELEGRAM_BOT_USERNAME or None
    return {
        "bot_username": username,
        "bot_url": f"https://t.me/{username}" if username else None,
        "instructions": [
            "Open Telegram and search for the bot",
            "Send /start to the bot",
            "The bot will reply with your numeric Chat ID",
            "Paste the Chat ID in the field below and click Save",
        ],
    }
