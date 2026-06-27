from datetime import date, datetime, timezone
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, status
from pymongo import ReturnDocument

from app.core.db import get_db
from app.core.redis import get_redis
from app.models.watch import (
    CreateWatchRequest,
    PatchWatchRequest,
    SnapshotResponse,
    WatchResponse,
)
from app.services.authz import CurrentUser
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/watches", tags=["watches"])

PLAN_LIMITS: dict[str, int] = {"free": 3, "pro": 30, "team": 150}
MANUAL_CHECK_COOLDOWN = 300  # seconds


def _parse_oid(watch_id: str) -> ObjectId:
    try:
        return ObjectId(watch_id)
    except (InvalidId, Exception):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Watch not found"},
        )


async def _get_watch(watch_id: str, user_id: ObjectId) -> dict:
    db = get_db()
    oid = _parse_oid(watch_id)
    watch = await db.watches.find_one({"_id": oid})
    if watch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Watch not found"},
        )
    if watch["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Access denied"},
        )
    return watch


def _doc_to_response(doc: dict) -> WatchResponse:
    return WatchResponse(
        watch_id=str(doc["_id"]),
        user_id=str(doc["user_id"]),
        origin=doc["origin"],
        destination=doc["destination"],
        date_mode=doc["date_mode"],
        depart_date=doc.get("depart_date"),
        return_date=doc.get("return_date"),
        date_from=doc.get("date_from"),
        date_to=doc.get("date_to"),
        passengers=doc["passengers"],
        cabin=doc["cabin"],
        rule=doc["rule"],
        active=doc["active"],
        lowest_seen=doc.get("lowest_seen"),
        lowest_seen_at=doc.get("lowest_seen_at"),
        last_checked_at=doc.get("last_checked_at"),
        last_alerted_at=doc.get("last_alerted_at"),
        last_offer=doc.get("last_offer"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_watch(body: CreateWatchRequest, current_user: CurrentUser) -> WatchResponse:
    db = get_db()
    plan = current_user.get("plan", "free")
    limit = PLAN_LIMITS.get(plan, 3)
    count = await db.watches.count_documents({"user_id": current_user["_id"], "active": True})
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "plan_limit_reached", "limit": limit, "current": count},
        )

    now = datetime.now(timezone.utc)
    doc: dict = {
        "user_id": current_user["_id"],
        "origin": body.origin,
        "destination": body.destination,
        "date_mode": body.date_mode,
        "depart_date": body.depart_date.isoformat() if body.depart_date else None,
        "return_date": body.return_date.isoformat() if body.return_date else None,
        "date_from": body.date_from.isoformat() if body.date_from else None,
        "date_to": body.date_to.isoformat() if body.date_to else None,
        "passengers": body.passengers,
        "cabin": body.cabin,
        "rule": body.rule.model_dump(exclude_none=True),
        "active": True,
        "lowest_seen": None,
        "lowest_seen_at": None,
        "last_checked_at": None,
        "last_alerted_at": None,
        "last_offer": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.watches.insert_one(doc)
    doc["_id"] = result.inserted_id

    celery_app.send_task("app.workers.tasks.poll_watch", args=[str(result.inserted_id)])

    return _doc_to_response(doc)


@router.get("")
async def list_watches(current_user: CurrentUser) -> list[WatchResponse]:
    db = get_db()
    cursor = db.watches.find({"user_id": current_user["_id"]})
    return [_doc_to_response(doc) async for doc in cursor]


@router.get("/{watch_id}")
async def get_watch(watch_id: str, current_user: CurrentUser) -> WatchResponse:
    watch = await _get_watch(watch_id, current_user["_id"])
    return _doc_to_response(watch)


@router.patch("/{watch_id}")
async def patch_watch(
    watch_id: str, body: PatchWatchRequest, current_user: CurrentUser
) -> WatchResponse:
    if body.origin is not None or body.destination is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "field_immutable", "detail": "origin and destination cannot be changed"},
        )

    watch = await _get_watch(watch_id, current_user["_id"])
    db = get_db()

    update: dict = {"updated_at": datetime.now(timezone.utc)}
    if "active" in body.model_fields_set:
        update["active"] = body.active
    if "rule" in body.model_fields_set and body.rule is not None:
        update["rule"] = body.rule.model_dump(exclude_none=True)

    if len(update) == 1:
        return _doc_to_response(watch)

    updated = await db.watches.find_one_and_update(
        {"_id": watch["_id"]},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    return _doc_to_response(updated)


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(watch_id: str, current_user: CurrentUser) -> None:
    watch = await _get_watch(watch_id, current_user["_id"])
    db = get_db()
    oid = watch["_id"]

    await db.price_snapshots.delete_many({"watch_id": oid})
    await db.alerts.delete_many({"watch_id": oid})
    await db.watches.delete_one({"_id": oid})


@router.post("/{watch_id}/check", status_code=status.HTTP_202_ACCEPTED)
async def check_now(watch_id: str, current_user: CurrentUser) -> dict:
    watch = await _get_watch(watch_id, current_user["_id"])

    r = await get_redis()
    cooldown_key = f"manual_check:{watch_id}"
    ttl = await r.ttl(cooldown_key)
    if ttl > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "check_cooldown", "retry_after": ttl},
        )

    await r.setex(cooldown_key, MANUAL_CHECK_COOLDOWN, "1")
    task = celery_app.send_task("app.workers.tasks.poll_watch", args=[str(watch["_id"])])
    return {"job_id": task.id}


@router.get("/{watch_id}/snapshots")
async def get_snapshots(
    watch_id: str,
    current_user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[SnapshotResponse]:
    watch = await _get_watch(watch_id, current_user["_id"])
    db = get_db()

    query: dict = {"watch_id": watch["_id"]}
    ts_filter: dict = {}
    if from_date:
        ts_filter["$gte"] = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc)
    if to_date:
        ts_filter["$lte"] = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc)
    if ts_filter:
        query["checked_at"] = ts_filter

    cursor = db.price_snapshots.find(query).sort("checked_at", 1).limit(limit)
    return [
        SnapshotResponse(
            checked_at=doc["checked_at"],
            price=doc.get("price"),
            airline=doc.get("airline"),
            airline_name=doc.get("airline_name"),
            stops=doc.get("stops"),
        )
        async for doc in cursor
    ]
