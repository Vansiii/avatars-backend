from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.models import User, Character, CharacterLimit
from app.schemas.character import (
    CharacterCreate,
    CharacterResponse,
    CharacterSelectRequest,
    CharacterCreateResponse,
    CharacterRedoResponse,
    CharacterVariation,
)
from app.services.image_provider import build_character_prompt, generate_character_variations
from app.services.nsfw_filter import check_text_nsfw, check_image_bytes_nsfw, log_nsfw_rejection

router = APIRouter(prefix="/api/v1/characters", tags=["characters"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024
MIN_DESCRIPTION_LENGTH = 10
MAX_DESCRIPTION_LENGTH = 500


def get_week_start():
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    return (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)


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


@router.post("", response_model=CharacterCreateResponse, status_code=201)
async def create_character(
    name: str = Form(...),
    description: str | None = Form(None),
    category: str = Form(...),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea un nuevo personaje con 3 variaciones iniciales."""
    limits = get_or_create_character_limit(db, current_user.id)
    if limits.characters_used >= 2:
        raise HTTPException(
            status_code=403,
            detail="Límite semanal de personajes alcanzado",
            headers={"x-error-code": "CHAR_001"},
        )

    valid_categories = ["deportes", "noticias", "entretenimiento"]
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Categoría no válida. Opciones: {', '.join(valid_categories)}"
        )

    if description:
        if len(description) < MIN_DESCRIPTION_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"La descripción debe tener al menos {MIN_DESCRIPTION_LENGTH} caracteres",
                headers={"x-error-code": "GEN_001"},
            )
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"La descripción no puede superar {MAX_DESCRIPTION_LENGTH} caracteres",
                headers={"x-error-code": "GEN_001"},
            )
        is_safe = await check_text_nsfw(description)
        if not is_safe:
            log_nsfw_rejection("text", "description contains NSFW content", current_user.id)
            raise HTTPException(
                status_code=422,
                detail="El contenido de la descripción no es apto",
                headers={"x-error-code": "GEN_004"},
            )

    if file:
        valid_formats = ["image/jpeg", "image/png", "image/webp"]
        if file.content_type not in valid_formats:
            raise HTTPException(
                status_code=400,
                detail="Formato de imagen no soportado. Use JPEG, PNG o WEBP",
                headers={"x-error-code": "GEN_001"},
            )
        image_bytes = await file.read()
        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=400,
                detail="La imagen no puede superar 10 MB",
                headers={"x-error-code": "GEN_002"},
            )
        is_safe = await check_image_bytes_nsfw(image_bytes)
        if not is_safe:
            log_nsfw_rejection("image", "uploaded image flagged as NSFW", current_user.id)
            raise HTTPException(
                status_code=422,
                detail="La imagen subida no es apta",
                headers={"x-error-code": "GEN_004"},
            )

    prompt = build_character_prompt(name=name, description=description, category=category)
    variations_urls = await generate_character_variations(prompt, count=3)

    import json
    consistency_data = json.dumps({
        "all_variations": variations_urls,  # Acumula todas las variaciones
        "current_batch": variations_urls,   # Lote actual
        "redos_used": 0,
    })

    character = Character(
        user_id=current_user.id,
        name=name,
        description=description,
        category=category,
        status="draft",
        consistency_data=consistency_data,
    )
    db.add(character)
    db.commit()
    db.refresh(character)

    variations = [
        CharacterVariation(index=i, image_url=url)
        for i, url in enumerate(variations_urls)
    ]

    return CharacterCreateResponse(
        character_id=character.id,
        variations=variations,
        redos_remaining=3,
        estimated_seconds=30,
    )


@router.get("", response_model=list[CharacterResponse])
def list_characters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista los personajes del usuario actual."""
    return db.query(Character).filter(Character.user_id == current_user.id).all()


@router.get("/{character_id}", response_model=CharacterResponse)
def get_character(
    character_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene un personaje por ID."""
    character = db.query(Character).filter(
        Character.id == character_id,
        Character.user_id == current_user.id,
    ).first()
    if not character:
        raise HTTPException(status_code=404, detail="Personaje no encontrado")
    return character


@router.post("/{character_id}/select", response_model=CharacterResponse)
def select_variation(
    character_id: str,
    request: CharacterSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Selecciona una variación del personaje. Solo al seleccionar se decrementa el límite."""
    character = db.query(Character).filter(
        Character.id == character_id,
        Character.user_id == current_user.id,
    ).first()
    if not character:
        raise HTTPException(status_code=404, detail="Personaje no encontrado")

    if character.status != "draft":
        raise HTTPException(status_code=400, detail="El personaje ya fue seleccionado")

    import json
    try:
        data = json.loads(character.consistency_data) if character.consistency_data else {}
        all_variations = data.get("all_variations", [])
    except (json.JSONDecodeError, TypeError):
        all_variations = []

    if request.variation_index < 0 or request.variation_index >= len(all_variations):
        raise HTTPException(status_code=400, detail="Índice de variación inválido")

    character.generated_image_url = all_variations[request.variation_index]
    character.reference_image_url = all_variations[request.variation_index]
    character.status = "active"
    character.updated_at = datetime.now(timezone.utc)

    limits = get_or_create_character_limit(db, current_user.id)
    limits.characters_used += 1

    db.commit()
    db.refresh(character)

    return character


@router.post("/{character_id}/redo", response_model=CharacterRedoResponse)
async def redo_character(
    character_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Genera 3 nuevas variaciones y las agrega a las existentes.

    El usuario puede elegir de TODAS las variaciones (anteriores + nuevas).
    """
    character = db.query(Character).filter(
        Character.id == character_id,
        Character.user_id == current_user.id,
    ).first()
    if not character:
        raise HTTPException(status_code=404, detail="Personaje no encontrado")

    if character.status != "draft":
        raise HTTPException(status_code=400, detail="El personaje ya fue seleccionado")

    import json
    try:
        data = json.loads(character.consistency_data) if character.consistency_data else {}
        all_variations = data.get("all_variations", [])
        redos_used = data.get("redos_used", 0)
    except (json.JSONDecodeError, TypeError):
        all_variations = []
        redos_used = 0

    if redos_used >= 3:
        raise HTTPException(
            status_code=400,
            detail="Máximo 3 rehacers alcanzados. Debe seleccionar una variación."
        )

    # Generar 3 nuevas variaciones
    prompt = build_character_prompt(
        name=character.name,
        description=character.description,
        category=character.category,
    )
    new_variations = await generate_character_variations(prompt, count=3)

    # Acumular: agregar nuevas a las existentes
    all_variations = all_variations + new_variations

    character.consistency_data = json.dumps({
        "all_variations": all_variations,
        "current_batch": new_variations,
        "redos_used": redos_used + 1,
    })
    db.commit()

    # Retornar TODAS las variaciones (anteriores + nuevas)
    all_indexed = [
        CharacterVariation(index=i, image_url=url)
        for i, url in enumerate(all_variations)
    ]

    return CharacterRedoResponse(
        character_id=character.id,
        variations=all_indexed,
        redos_remaining=3 - (redos_used + 1),
    )
