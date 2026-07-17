from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth.dependencies import require_admin
from app.database.database import get_db
from app.models.models import User, Character, Spot, CharacterLimit
from app.schemas.admin import MetricsResponse, UserLimitsResponse, UserLimitsUpdate

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def get_week_start():
    """Obtiene el inicio de la semana actual (lunes 00:00 UTC)."""
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    return (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Obtiene métricas generales del sistema (solo admin)."""
    week_start = get_week_start()

    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    inactive_users = total_users - active_users

    # Personajes creados esta semana (todos los usuarios)
    characters_this_week = db.query(Character).filter(
        Character.created_at >= week_start
    ).count()

    # Spots generados esta semana
    spots_this_week = db.query(Spot).filter(
        Spot.created_at >= week_start
    ).count()

    return MetricsResponse(
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        characters_this_week=characters_this_week,
        spots_this_week=spots_this_week,
    )


@router.get("/users/{user_id}/limits", response_model=UserLimitsResponse)
def get_user_limits(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Obtiene los límites de un usuario específico."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    week_start = get_week_start()
    limits = db.query(CharacterLimit).filter(
        CharacterLimit.user_id == user_id,
        CharacterLimit.week_start >= week_start,
    ).first()

    if not limits:
        # Crear registro de límites si no existe
        limits = CharacterLimit(
            user_id=user_id,
            week_start=week_start,
            characters_used=0,
            spots_used=0,
        )
        db.add(limits)
        db.commit()
        db.refresh(limits)

    return UserLimitsResponse(
        user_id=user_id,
        user_email=user.email,
        user_name=user.display_name,
        week_start=week_start,
        characters_used=limits.characters_used,
        characters_limit=2,
        characters_remaining=max(0, 2 - limits.characters_used),
        spots_used=limits.spots_used,
        spots_limit=5,
        spots_remaining=max(0, 5 - limits.spots_used),
    )


@router.put("/users/{user_id}/limits", response_model=UserLimitsResponse)
def update_user_limits(
    user_id: str,
    request: UserLimitsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Modifica los límites de un usuario (solo admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

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

    if request.characters_limit is not None:
        # Permitir que el admin ajuste el límite (reseteando el contador si se sube)
        if request.characters_limit > limits.characters_used:
            limits.characters_used = max(0, request.characters_limit - 2)

    if request.spots_limit is not None:
        if request.spots_limit > limits.spots_used:
            limits.spots_used = max(0, request.spots_limit - 5)

    db.commit()
    db.refresh(limits)

    return UserLimitsResponse(
        user_id=user_id,
        user_email=user.email,
        user_name=user.display_name,
        week_start=week_start,
        characters_used=limits.characters_used,
        characters_limit=2,
        characters_remaining=max(0, 2 - limits.characters_used),
        spots_used=limits.spots_used,
        spots_limit=5,
        spots_remaining=max(0, 5 - limits.spots_used),
    )
