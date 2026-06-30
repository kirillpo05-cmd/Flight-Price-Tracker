from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import MongoClient
from pymongo.database import Database as SyncDatabase

from app.core.config import settings

# --- Async client (FastAPI / Motor) ---

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGO_URL)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGO_DB]


# --- Sync client (Celery workers / pymongo) ---

_sync_client: MongoClient | None = None


def get_sync_client() -> MongoClient:
    global _sync_client
    if _sync_client is None:
        _sync_client = MongoClient(settings.MONGO_URL)
    return _sync_client


def get_sync_db() -> SyncDatabase:
    return get_sync_client()[settings.MONGO_DB]


async def ensure_indexes() -> None:
    db = get_db()

    await db.users.create_index("email", unique=True)

    await db.watches.create_index("user_id")
    await db.watches.create_index("active")
    await db.watches.create_index([("user_id", 1), ("active", 1)])

    await db.alerts.create_index([("watch_id", 1), ("triggered_at", -1)])
    await db.alerts.create_index([("user_id", 1), ("triggered_at", -1)])

    # price_snapshots is time-series; create only if it doesn't exist yet
    existing = await db.list_collection_names()
    if "price_snapshots" not in existing:
        await db.create_collection(
            "price_snapshots",
            timeseries={
                "timeField": "checked_at",
                "metaField": "watch_id",
                "granularity": "hours",
            },
        )
