from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.db import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import (
    ChangePasswordRequest,
    LoginRequest,
    PatchMeRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.authz import CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_response(user: dict) -> UserResponse:
    return UserResponse(
        user_id=str(user["_id"]),
        email=user["email"],
        plan=user["plan"],
        telegram_chat_id=user.get("telegram_chat_id"),
        telegram_connected_at=user.get("telegram_connected_at"),
        created_at=user["created_at"],
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> dict:
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "plan": "free",
        "telegram_chat_id": None,
        "telegram_connected_at": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "email_taken", "detail": "Email is already registered"},
        )
    return {"user_id": str(result.inserted_id), "email": body.email}


@router.post("/login")
async def login(body: LoginRequest) -> TokenResponse:
    db = get_db()
    user = await db.users.find_one({"email": body.email})
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "detail": "Invalid email or password"},
        )
    return TokenResponse(access_token=create_access_token(str(user["_id"]), user["plan"]))


@router.get("/me")
async def get_me(current_user: CurrentUser) -> UserResponse:
    return _to_response(current_user)


@router.patch("/me")
async def patch_me(body: PatchMeRequest, current_user: CurrentUser) -> UserResponse:
    db = get_db()
    now = datetime.now(timezone.utc)
    update: dict = {"updated_at": now}

    if "telegram_chat_id" in body.model_fields_set:
        if body.telegram_chat_id is not None:
            update["telegram_chat_id"] = body.telegram_chat_id
            update["telegram_connected_at"] = now
        else:
            update["telegram_chat_id"] = None
            update["telegram_connected_at"] = None

    if "email" in body.model_fields_set and body.email is not None:
        if body.email != current_user["email"]:
            exists = await db.users.find_one(
                {"email": body.email, "_id": {"$ne": current_user["_id"]}}
            )
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "email_taken", "detail": "Email is already registered"},
                )
        update["email"] = body.email

    if len(update) == 1:
        return _to_response(current_user)

    user = await db.users.find_one_and_update(
        {"_id": current_user["_id"]},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    return _to_response(user)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, current_user: CurrentUser) -> dict:
    if not verify_password(body.old_password, current_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "detail": "Old password is incorrect"},
        )
    db = get_db()
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "password_hash": hash_password(body.new_password),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return {"message": "password_changed"}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(current_user: CurrentUser) -> None:
    db = get_db()
    user_id = current_user["_id"]

    watch_ids = [w["_id"] async for w in db.watches.find({"user_id": user_id}, {"_id": 1})]
    if watch_ids:
        await db.price_snapshots.delete_many({"watch_id": {"$in": watch_ids}})
        await db.alerts.delete_many({"watch_id": {"$in": watch_ids}})
        await db.watches.delete_many({"user_id": user_id})

    await db.users.delete_one({"_id": user_id})
