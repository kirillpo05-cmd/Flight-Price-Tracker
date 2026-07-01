from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, status

from app.core.db import get_db
from app.models.alert import AlertResponse
from app.services.authz import CurrentUser

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _doc_to_response(doc: dict) -> AlertResponse:
    return AlertResponse(
        alert_id=str(doc["_id"]),
        watch_id=str(doc["watch_id"]),
        rule_type=doc["rule_type"],
        triggered_at=doc["triggered_at"],
        price=doc.get("price"),
        offer=doc.get("offer"),
        channel=doc["channel"],
        status=doc["status"],
        error=doc.get("error"),
    )


@router.get("")
async def list_alerts(
    current_user: CurrentUser,
    watch_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlertResponse]:
    db = get_db()
    query: dict = {"user_id": current_user["_id"]}

    if watch_id is not None:
        try:
            query["watch_id"] = ObjectId(watch_id)
        except (InvalidId, Exception):
            return []

    cursor = (
        db.alerts.find(query)
        .sort("triggered_at", -1)
        .skip(offset)
        .limit(limit)
    )
    return [_doc_to_response(doc) async for doc in cursor]


@router.get("/{alert_id}")
async def get_alert(alert_id: str, current_user: CurrentUser) -> AlertResponse:
    try:
        oid = ObjectId(alert_id)
    except (InvalidId, Exception):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Alert not found"},
        )

    db = get_db()
    doc = await db.alerts.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "detail": "Alert not found"},
        )
    if doc["user_id"] != current_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Access denied"},
        )
    return _doc_to_response(doc)
