import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.models import User, Character, Spot
from app.schemas.spot import (
    SpotCreateRequest,
    SpotCreateResponse,
    SpotResponse,
    SpotSelectRequest,
    SpotRedoResponse,
    SpotVariation,
)
from app.services.video_provider import generate_spot_variations, DURATION_SECONDS
from app.services.limits import get_or_create_character_limit
from app.services.nsfw_filter import check_text_nsfw, log_nsfw_rejection
from app.config.settings import settings

router = APIRouter(prefix="/api/v1/spots", tags=["spots"])

VALID_TYPES = {"short", "long"}

# La duración real del video la marca el TTS del guión, no un parámetro de HeyGen
# (ver video_provider.py) — pero antes el rango de caracteres era el mismo para
# "short" y "long" (10-500), así que un spot "corto" podía llevar un guión de
# 500 caracteres y salir bastante más largo que 3-5s, gastando más crédito real
# del esperado. Rangos calculados a ritmo de narración natural (~2.5 palabras/s,
# ~6 caracteres/palabra) para que el tipo elegido sí acote la duración/costo.
SCRIPT_LENGTH_RANGES = {
    "short": (10, 120),   # ~3-8s de narración
    "long": (120, 500),   # ~8-30s de narración
}


def _get_owned_spot(db: Session, spot_id: str, user_id: str) -> Spot:
    spot = db.query(Spot).filter(Spot.id == spot_id, Spot.user_id == user_id).first()
    if not spot:
        raise HTTPException(status_code=404, detail="Spot no encontrado")
    return spot


def _load_variations(spot: Spot) -> tuple[list[str], int]:
    try:
        data = json.loads(spot.variations_data) if spot.variations_data else {}
        return data.get("all_variations", []), data.get("redos_used", 0)
    except (json.JSONDecodeError, TypeError):
        return [], 0


@router.post("", response_model=SpotCreateResponse, status_code=201)
async def create_spot(
    request: SpotCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Genera 3 variaciones de un spot de video a partir de un personaje ya activo."""
    character = db.query(Character).filter(
        Character.id == request.character_id,
        Character.user_id == current_user.id,
    ).first()
    if not character:
        raise HTTPException(status_code=404, detail="Personaje no encontrado")
    if character.status != "active" or not (character.heygen_avatar_id or character.reference_image_url):
        raise HTTPException(
            status_code=400,
            detail="El personaje debe estar activo (con una variación seleccionada) para generar spots",
        )

    if request.type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de video inválido. Use 'short' o 'long'")

    min_len, max_len = SCRIPT_LENGTH_RANGES[request.type]
    if len(request.script) < min_len or len(request.script) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"Para un spot '{request.type}', el guión debe tener entre {min_len} y {max_len} caracteres",
            headers={"x-error-code": "GEN_001"},
        )

    is_safe = await check_text_nsfw(request.script)
    if not is_safe:
        log_nsfw_rejection("text", "spot script contains NSFW content", current_user.id)
        raise HTTPException(
            status_code=422,
            detail="El contenido del guión no es apto",
            headers={"x-error-code": "GEN_004"},
        )

    variations_urls = await generate_spot_variations(
        character.reference_image_url, request.script, request.type,
        count=settings.HEYGEN_SPOT_VARIATIONS,
        voice_id=character.heygen_voice_id,
        avatar_id=character.heygen_avatar_id,
    )

    spot = Spot(
        character_id=character.id,
        user_id=current_user.id,
        script=request.script,
        type=request.type,
        status="draft",
        duration_seconds=str(DURATION_SECONDS[request.type]),
        variations_data=json.dumps({
            "all_variations": variations_urls,
            "current_batch": variations_urls,
            "redos_used": 0,
        }),
    )
    db.add(spot)
    db.commit()
    db.refresh(spot)

    variations = [SpotVariation(index=i, video_url=url) for i, url in enumerate(variations_urls)]

    return SpotCreateResponse(spot_id=spot.id, variations=variations, redos_remaining=3)


@router.get("", response_model=list[SpotResponse])
def list_spots(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lista los spots del usuario actual."""
    return db.query(Spot).filter(Spot.user_id == current_user.id).all()


@router.get("/{spot_id}", response_model=SpotResponse)
def get_spot(
    spot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene un spot por ID."""
    return _get_owned_spot(db, spot_id, current_user.id)


@router.post("/{spot_id}/select", response_model=SpotResponse)
def select_spot_variation(
    spot_id: str,
    request: SpotSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Selecciona una variación. Solo al elegir se decrementa el límite semanal (SOUL.md §5)."""
    spot = _get_owned_spot(db, spot_id, current_user.id)
    if spot.status != "draft":
        raise HTTPException(status_code=400, detail="El spot ya fue seleccionado")

    all_variations, _ = _load_variations(spot)
    if request.variation_index < 0 or request.variation_index >= len(all_variations):
        raise HTTPException(status_code=400, detail="Índice de variación inválido")

    spot.output_url = all_variations[request.variation_index]
    spot.status = "ready"

    limits = get_or_create_character_limit(db, current_user.id)
    limits.spots_used += 1

    db.commit()
    db.refresh(spot)
    return spot


@router.post("/{spot_id}/redo", response_model=SpotRedoResponse)
async def redo_spot(
    spot_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Genera 3 nuevas variaciones del spot (máx 3 rehacers gratis, SOUL.md §5)."""
    spot = _get_owned_spot(db, spot_id, current_user.id)
    if spot.status != "draft":
        raise HTTPException(status_code=400, detail="El spot ya fue seleccionado")

    all_variations, redos_used = _load_variations(spot)
    if redos_used >= 3:
        raise HTTPException(
            status_code=400,
            detail="Máximo 3 rehacers alcanzados. Debe seleccionar una variación.",
        )

    character = db.query(Character).filter(Character.id == spot.character_id).first()
    new_variations = await generate_spot_variations(
        character.reference_image_url, spot.script, spot.type,
        count=settings.HEYGEN_SPOT_VARIATIONS,
        voice_id=character.heygen_voice_id,
        avatar_id=character.heygen_avatar_id,
    )

    all_variations = all_variations + new_variations
    spot.variations_data = json.dumps({
        "all_variations": all_variations,
        "current_batch": new_variations,
        "redos_used": redos_used + 1,
    })
    db.commit()

    all_indexed = [SpotVariation(index=i, video_url=url) for i, url in enumerate(all_variations)]
    return SpotRedoResponse(
        spot_id=spot.id,
        variations=all_indexed,
        redos_remaining=3 - (redos_used + 1),
    )
