import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DatabaseSession

from app.auth.auth_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.auth.dependencies import get_current_token_claims, get_current_user
from app.database.database import get_db
from app.middleware.degraded import access_token_ttl, enter_degraded, is_degraded
from app.models.refresh_token import RefreshToken
from app.models.session import Session as AuthSession
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserLogin, UserResponse, UserUpdate

router = APIRouter()
logger = logging.getLogger(__name__)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _token_expiry(claims: dict) -> datetime:
    expiry = claims.get("exp")
    if not isinstance(expiry, (int, float)):
        raise _unauthorized()
    return datetime.fromtimestamp(expiry, timezone.utc)


def _record_tokens(
    user_id: str, sid: uuid.UUID, request: Request
) -> tuple[str, str, datetime]:
    refresh_token = create_refresh_token({"sub": str(user_id)}, session_id=sid)
    refresh_expiry = _token_expiry(decode_token(refresh_token) or {})
    access_token = create_access_token(
        {"sub": str(user_id)},
        session_id=sid,
        expires_delta=access_token_ttl(request),
    )
    return access_token, refresh_token, refresh_expiry


def _add_session_token_pair(
    db: DatabaseSession,
    *,
    user_id: str,
    sid: uuid.UUID,
    refresh_token: str,
    refresh_expiry: datetime,
    legacy_token_hash: str | None = None,
) -> None:
    refresh_id = uuid.uuid4()
    refresh_hash = hash_refresh_token(refresh_token)
    session = AuthSession(
        sid=sid,
        user_id=user_id,
        expires_at=refresh_expiry,
        refresh_token_hash=refresh_hash,
    )
    active_record = RefreshToken(
        id=refresh_id,
        token_hash=refresh_hash,
        user_id=user_id,
        session_id=sid,
        expires_at=refresh_expiry,
    )
    db.add(session)
    db.add(active_record)
    if legacy_token_hash is not None:
        db.add(
            RefreshToken(
                id=uuid.uuid4(),
                token_hash=legacy_token_hash,
                user_id=user_id,
                session_id=sid,
                expires_at=refresh_expiry,
                revoked=True,
                revoked_at=datetime.now(timezone.utc),
                replaced_by=refresh_id,
            )
        )


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: DatabaseSession = Depends(get_db)):
    # Password strength check
    password = user_in.password
    if (
        len(password) < 8
        or not any(c.isupper() for c in password)
        or not any(c.isdigit() for c in password)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener al menos 8 caracteres, una mayúscula y un número.",
        )

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        return {
            "message": "Si el correo es válido, se enviará un enlace de confirmación."
        }

    new_user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        plan_tier="free",
        credits_used=0,
        credits_limit=5,
        is_active=True,
        is_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Si el correo es válido, se enviará un enlace de confirmación."}


@router.post("/auth/login", response_model=Token)
async def login(
    user_in: UserLogin,
    request: Request,
    db: DatabaseSession = Depends(get_db),
) -> Token:
    user = db.query(User).filter(User.email == user_in.email).first()
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cuenta inactiva"
        )

    sid = uuid.uuid4()
    access_token, refresh_token, refresh_expiry = _record_tokens(user.id, sid, request)
    try:
        _add_session_token_pair(
            db,
            user_id=user.id,
            sid=sid,
            refresh_token=refresh_token,
            refresh_expiry=refresh_expiry,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info("Session created", extra={"sid": str(sid), "user_id": str(user.id)})
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


async def _upgrade_legacy_refresh(
    token_data: dict,
    presented_token: str,
    request: Request,
    db: DatabaseSession,
) -> Token:
    user_id = token_data.get("sub")
    if not user_id:
        raise _unauthorized()

    legacy_hash = hash_refresh_token(presented_token)
    if db.query(RefreshToken).filter(RefreshToken.token_hash == legacy_hash).first():
        logger.warning(
            "Legacy refresh token replay detected", extra={"user_id": str(user_id)}
        )
        raise _unauthorized()

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise _unauthorized()

    sid = uuid.uuid4()
    access_token, refresh_token, refresh_expiry = _record_tokens(user.id, sid, request)
    try:
        _add_session_token_pair(
            db,
            user_id=user.id,
            sid=sid,
            refresh_token=refresh_token,
            refresh_expiry=refresh_expiry,
            legacy_token_hash=legacy_hash,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "Legacy refresh upgraded", extra={"sid": str(sid), "user_id": str(user.id)}
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/auth/refresh", response_model=Token)
async def refresh_token(
    payload: RefreshTokenRequest,
    request: Request,
    db: DatabaseSession = Depends(get_db),
) -> Token:
    token_data = decode_token(payload.refresh_token)
    if (
        not token_data
        or token_data.get("refresh") is not True
        or not token_data.get("sub")
    ):
        logger.warning("Invalid refresh token presented")
        raise _unauthorized()

    if not token_data.get("sid"):
        return await _upgrade_legacy_refresh(
            token_data, payload.refresh_token, request, db
        )

    user_id = token_data["sub"]
    sid = token_data["sid"]
    old_hash = hash_refresh_token(payload.refresh_token)
    old_record = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == old_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if (
        old_record is None
        or str(old_record.user_id) != str(user_id)
        or str(old_record.session_id) != str(sid)
    ):
        logger.warning(
            "Refresh token replay detected",
            extra={"sid": str(sid), "jti": token_data.get("jti")},
        )
        raise _unauthorized()

    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.sid == sid,
            AuthSession.user_id == user_id,
            AuthSession.revoked.is_(False),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
        .first()
    )
    if session is None:
        logger.warning(
            "Refresh rejected for revoked or expired session", extra={"sid": str(sid)}
        )
        raise _unauthorized()

    new_id = uuid.uuid4()
    new_refresh = create_refresh_token({"sub": str(user_id)}, session_id=sid)
    new_hash = hash_refresh_token(new_refresh)
    new_expiry = _token_expiry(decode_token(new_refresh) or {})
    try:
        updated = (
            db.query(RefreshToken)
            .filter(RefreshToken.id == old_record.id, RefreshToken.revoked.is_(False))
            .update(
                {
                    RefreshToken.revoked: True,
                    RefreshToken.revoked_at: datetime.now(timezone.utc),
                    RefreshToken.replaced_by: new_id,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.rollback()
            logger.warning(
                "Refresh token replay detected",
                extra={"sid": str(sid), "jti": token_data.get("jti")},
            )
            raise _unauthorized()
        db.add(
            RefreshToken(
                id=new_id,
                token_hash=new_hash,
                user_id=user_id,
                session_id=sid,
                expires_at=new_expiry,
            )
        )
        session.refresh_token_hash = new_hash
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    access_token = create_access_token(
        {"sub": str(user_id)}, session_id=sid, expires_delta=access_token_ttl(request)
    )
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/auth/logout")
async def logout(
    request: Request,
    claims: dict = Depends(get_current_token_claims),
    db: DatabaseSession = Depends(get_db),
    body: LogoutRequest | None = None,
) -> dict[str, str]:
    sid = claims.get("sid")
    user_id = claims.get("sub")
    if not sid or not user_id:
        raise _unauthorized()

    try:
        (
            db.query(AuthSession)
            .filter(
                AuthSession.sid == sid,
                AuthSession.user_id == user_id,
                AuthSession.revoked.is_(False),
            )
            .update(
                {
                    AuthSession.revoked: True,
                    AuthSession.revoked_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        if body and body.refresh_token:
            token_hash = hash_refresh_token(body.refresh_token)
            (
                db.query(RefreshToken)
                .filter(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.user_id == user_id,
                    RefreshToken.session_id == sid,
                    RefreshToken.revoked.is_(False),
                )
                .update(
                    {
                        RefreshToken.revoked: True,
                        RefreshToken.revoked_at: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    try:
        redis = getattr(request.app.state, "redis", None)
        if redis is not None and not is_degraded(request):
            authorization = (
                request.headers.get("authorization", "")
                if hasattr(request, "headers")
                else ""
            )
            token = authorization.removeprefix("Bearer ")
            token_expiry = (
                (decode_token(token) or {}).get("exp") if token else claims.get("exp")
            )
            remaining_seconds = max(
                1, int(token_expiry or 0) - int(datetime.now(timezone.utc).timestamp())
            )
            await redis.set(f"blacklist:v1:sid:{sid}", "1", ex=remaining_seconds)
    except Exception:
        enter_degraded(request.app, reason="logout_blacklist_write_failed")

    logger.info("Session revoked", extra={"sid": str(sid), "user_id": str(user_id)})
    return {"message": "Sesión cerrada correctamente"}


# Profile endpoints under /users/me
@router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/users/me", response_model=UserResponse)
def update_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: DatabaseSession = Depends(get_db),
):
    if user_update.display_name is not None:
        current_user.display_name = user_update.display_name
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url
    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/users/me", status_code=status.HTTP_200_OK)
def delete_me(
    current_user: User = Depends(get_current_user),
    db: DatabaseSession = Depends(get_db),
):
    db.delete(current_user)
    db.commit()
    return {"message": "Cuenta eliminada permanentemente"}
