import bcrypt
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config.settings import settings


# Password Hashing Utilities using bcrypt directly (prevents passlib deprecation issues on modern Python)
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def _token_claims(
    data: dict,
    *,
    session_id: str | uuid.UUID | None,
    expires_delta: Optional[timedelta],
    default_expiry: timedelta,
) -> dict:
    now = datetime.now(timezone.utc)
    claims = data.copy()
    claims.update(
        {
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": now + (expires_delta or default_expiry),
        }
    )
    if session_id is not None:
        claims["sid"] = str(session_id)
    return claims


# JWT Token Utilities
def create_access_token(
    data: dict,
    *,
    session_id: str | uuid.UUID | None = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    claims = _token_claims(
        data,
        session_id=session_id,
        expires_delta=expires_delta,
        default_expiry=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    claims.pop("refresh", None)
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    data: dict,
    *,
    session_id: str | uuid.UUID | None = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    claims = _token_claims(
        data,
        session_id=session_id,
        expires_delta=expires_delta,
        default_expiry=timedelta(days=7),
    )
    claims["refresh"] = True
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
