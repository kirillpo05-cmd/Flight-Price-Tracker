from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from jose import jwt

from app.core.config import settings

_ph = PasswordHasher()

ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 3600


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _ph.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, Exception):
        return False


def create_access_token(user_id: str, plan: str) -> str:
    payload = {
        "sub": user_id,
        "plan": plan,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    # Raises jose.JWTError (including ExpiredSignatureError) on invalid/expired token
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
