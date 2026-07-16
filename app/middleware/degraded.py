"""Shared state transitions for Redis-degraded operation."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config.settings import settings
from app.database.database import SessionLocal
from app.models.session import Session

logger = logging.getLogger(__name__)

_BLACKLIST_PREFIX = "blacklist:v1:sid:"
_CACHE_PAGE_SIZE = 250


def enter_degraded(app, *, reason: str) -> None:
    """Enter degraded mode once, without exposing Redis connection details."""
    if getattr(app.state, "degraded", False):
        return

    app.state.degraded = True
    app.state.redis = None
    logger.warning(
        "Redis unavailable; entering degraded mode",
        extra={"reason": "redis_operation_failed"},
    )


def is_degraded(request) -> bool:
    """Return the current application health state without mutating it."""
    return bool(getattr(request.app.state, "degraded", False))


def access_token_ttl(request) -> timedelta:
    """Use a short access-token lifetime while Redis is unavailable."""
    minutes = (
        settings.DEGRADED_ACCESS_TOKEN_EXPIRE_MINUTES
        if is_degraded(request)
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return timedelta(minutes=minutes)


async def repopulate_blacklist_cache(app, redis_client) -> None:
    """Restore revoked, unexpired session entries to the Redis projection."""
    now = datetime.now(timezone.utc)
    last_sid = None
    db = SessionLocal()
    try:
        while True:
            statement = (
                select(Session)
                .where(Session.revoked.is_(True), Session.expires_at > now)
                .order_by(Session.sid)
                .limit(_CACHE_PAGE_SIZE)
            )
            if last_sid is not None:
                statement = statement.where(Session.sid > last_sid)

            sessions = db.execute(statement).scalars().all()
            if not sessions:
                return

            pipeline = redis_client.pipeline(transaction=False)
            for session in sessions:
                expires_at = session.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                ttl = max(1, int((expires_at - now).total_seconds() + 0.999999))
                pipeline.set(f"{_BLACKLIST_PREFIX}{session.sid}", "1", ex=ttl)

            await pipeline.execute()
            last_sid = sessions[-1].sid
            if len(sessions) < _CACHE_PAGE_SIZE:
                return
    finally:
        db.close()


async def recover_redis(app, redis_client) -> bool:
    """Promote a candidate Redis client only after blacklist cache warm-up."""
    try:
        await redis_client.ping()
        await repopulate_blacklist_cache(app, redis_client)
    except Exception:
        return False

    app.state.redis = redis_client
    app.state.degraded = False
    logger.info("Redis recovered; blacklist projection repopulated")
    return True
