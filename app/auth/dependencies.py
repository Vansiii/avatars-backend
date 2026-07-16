from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.auth_handler import decode_token
from app.database.database import get_db
from app.middleware.degraded import enter_degraded, is_degraded
from app.models.session import Session as AuthSession
from app.models.user import User

# Token URL corresponds to the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_token_claims(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict:
    """Extract claims from a valid access token without database access."""
    if not token:
        raise _unauthorized()

    payload = decode_token(token)
    if payload is None or payload.get("refresh"):
        raise _unauthorized()

    subject = payload.get("sub")
    if not subject:
        raise _unauthorized()

    return {
        "sub": subject,
        "sid": payload.get("sid"),
        "jti": payload.get("jti"),
        "iat": payload.get("iat"),
    }


async def _check_session_pg(db: DatabaseSession, sid: str, user_id: str) -> User:
    session = (
        db.query(AuthSession.sid)
        .filter(
            AuthSession.sid == sid,
            AuthSession.user_id == user_id,
            AuthSession.revoked.is_(False),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if session is None:
        raise _unauthorized()

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


async def get_current_user(
    request: Request,
    claims: dict = Depends(get_current_token_claims),
    db: DatabaseSession = Depends(get_db),
) -> User:
    sid = claims.get("sid")
    user_id = claims.get("sub")
    if not user_id:
        raise _unauthorized()

    # Pre-session legacy access tokens remain valid until their natural expiry.
    if sid is None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None or not user.is_active:
            raise _unauthorized()
        return user

    if not is_degraded(request):
        try:
            redis = getattr(request.app.state, "redis", None)
            if redis is None:
                raise RuntimeError("Redis client unavailable")
            if await redis.get(f"blacklist:v1:sid:{sid}"):
                raise _unauthorized()
            user = db.query(User).filter(User.id == user_id).first()
            if user is None or not user.is_active:
                raise _unauthorized()
            return user
        except HTTPException:
            raise
        except Exception:
            enter_degraded(request.app, reason="blacklist_check_failed")

    return await _check_session_pg(db, sid, user_id)
