from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.database.database import get_db
from app.models.models import User, Character, Spot
from app.schemas.admin import MetricsResponse, UserLimitsResponse, UserLimitsUpdate
from app.services.limits import get_effective_limits, get_or_create_character_limit, get_week_start

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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
    limits = get_or_create_character_limit(db, user_id)
    characters_limit, spots_limit = get_effective_limits(user)

    return UserLimitsResponse(
        user_id=user_id,
        user_email=user.email,
        user_name=user.display_name,
        week_start=week_start,
        characters_used=limits.characters_used,
        characters_limit=characters_limit,
        characters_remaining=max(0, characters_limit - limits.characters_used),
        spots_used=limits.spots_used,
        spots_limit=spots_limit,
        spots_remaining=max(0, spots_limit - limits.spots_used),
    )


@router.put("/users/{user_id}/limits", response_model=UserLimitsResponse)
def update_user_limits(
    user_id: str,
    request: UserLimitsUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Modifica el tope semanal de un usuario (override real, guardado en el propio usuario)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if request.characters_limit is not None:
        user.characters_limit_override = request.characters_limit
    if request.spots_limit is not None:
        user.spots_limit_override = request.spots_limit
    db.commit()
    db.refresh(user)

    week_start = get_week_start()
    limits = get_or_create_character_limit(db, user_id)
    characters_limit, spots_limit = get_effective_limits(user)

    return UserLimitsResponse(
        user_id=user_id,
        user_email=user.email,
        user_name=user.display_name,
        week_start=week_start,
        characters_used=limits.characters_used,
        characters_limit=characters_limit,
        characters_remaining=max(0, characters_limit - limits.characters_used),
        spots_used=limits.spots_used,
        spots_limit=spots_limit,
        spots_remaining=max(0, spots_limit - limits.spots_used),
    )
