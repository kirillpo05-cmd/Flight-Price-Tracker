from fastapi import APIRouter
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as aioredis

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    result: dict = {
        "status": "ok",
        "mongo": "ok",
        "redis": "ok",
        "scheduler_last_run": None,
        "active_watches": 0,
    }

    try:
        client = AsyncIOMotorClient(settings.MONGO_URL, serverSelectionTimeoutMS=2000)
        await client.admin.command("ping")
        db = client[settings.MONGO_DB]
        result["active_watches"] = await db.watches.count_documents({"active": True})
        client.close()
    except Exception:
        result["mongo"] = "error"
        result["status"] = "error"

    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        last_run = await r.get("scheduler:last_run")
        result["scheduler_last_run"] = last_run.decode() if last_run else None
        await r.aclose()
    except Exception:
        result["redis"] = "error"
        result["status"] = "error"

    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)
