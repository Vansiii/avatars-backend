"""Límites semanales de generación — única fuente de verdad.

Antes vivía duplicado en characters.py y admin.py, y el límite "configurable"
por el admin no existía en la DB (el endpoint solo manipulaba el contador de uso).
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.models import User, CharacterLimit


def get_week_start() -> datetime:
    """Lunes 00:00 UTC de la semana actual (SOUL.md §3: reset semanal)."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    return (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def get_or_create_character_limit(db: Session, user_id: str) -> CharacterLimit:
    week_start = get_week_start()
    limits = db.query(CharacterLimit).filter(
        CharacterLimit.user_id == user_id,
        CharacterLimit.week_start >= week_start,
    ).first()

    if not limits:
        limits = CharacterLimit(
            user_id=user_id,
            week_start=week_start,
            characters_used=0,
            spots_used=0,
        )
        db.add(limits)
        db.commit()
        db.refresh(limits)

    return limits


def get_effective_limits(user: User) -> tuple[int, int]:
    """Tope de (personajes, spots) para este usuario: override del admin si existe, si no el default."""
    characters_limit = (
        user.characters_limit_override
        if user.characters_limit_override is not None
        else settings.DEFAULT_CHARACTERS_LIMIT
    )
    spots_limit = (
        user.spots_limit_override
        if user.spots_limit_override is not None
        else settings.DEFAULT_SPOTS_LIMIT
    )
    return characters_limit, spots_limit
