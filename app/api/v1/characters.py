from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.models import User, Character, SpotCategory
from app.schemas.character import (
    CharacterResponse,
    CharacterVoiceRequest,
    HeygenVoice,
    CharacterFromPhotoResponse,
    HeygenCatalogResponse,
    CharacterConfirmRequest,
)
from app.services.video_provider import (
    list_spanish_voices,
    fetch_voice_preview,
    create_avatar_from_photo,
    list_public_avatar_looks,
)
from app.services.limits import get_or_create_character_limit
from app.services.nsfw_filter import check_image_bytes_nsfw, check_image_url_nsfw, log_nsfw_rejection

router = APIRouter(prefix="/api/v1/characters", tags=["characters"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024
VALID_IMAGE_FORMATS = ["image/jpeg", "image/png", "image/webp"]


def _valid_categories(db: Session) -> list[str]:
    # Las categorías las gestiona el admin (SpotCategory); no hay lista fija.
    return [c.name.lower() for c in db.query(SpotCategory).all()]


@router.post("/create-from-photo", response_model=CharacterFromPhotoResponse, status_code=201)
async def create_from_photo(
    name: str = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea un avatar animable de HeyGen a partir de una foto propia.

    A diferencia del flujo viejo (Pollinations, 3 variaciones gratis), esto
    es UN solo resultado determinístico que consume crédito real de HeyGen —
    por eso NO se persiste como Character acá. El frontend muestra el
    resultado y el usuario confirma con `POST /confirm` (o lo descarta sin
    dejar rastro en la DB).
    """
    if category not in _valid_categories(db):
        valid = ", ".join(_valid_categories(db)) or "ninguna configurada"
        raise HTTPException(status_code=400, detail=f"Categoría no válida. Opciones: {valid}")

    if file.content_type not in VALID_IMAGE_FORMATS:
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

    result = await create_avatar_from_photo(name, image_bytes, file.content_type)

    # SOUL.md §6: valida también la SALIDA, no solo la entrada.
    is_safe = await check_image_url_nsfw(result["preview_image_url"])
    if not is_safe:
        log_nsfw_rejection("generated_image", "heygen avatar flagged as NSFW", current_user.id)
        raise HTTPException(
            status_code=422,
            detail="No se pudo generar contenido apto. Intente con otra foto.",
            headers={"x-error-code": "GEN_004"},
        )

    return CharacterFromPhotoResponse(**result)


@router.get("/heygen-catalog", response_model=HeygenCatalogResponse)
async def get_heygen_catalog(token: str | None = None, current_user: User = Depends(get_current_user)):
    """Catálogo público de avatares de HeyGen, para elegir uno existente en vez de crear uno nuevo."""
    return await list_public_avatar_looks(token=token)


@router.post("/confirm", response_model=CharacterResponse, status_code=201)
def confirm_character(
    request: CharacterConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persiste el personaje elegido (por foto propia o catálogo) como activo.

    Es acá donde se cuenta contra el uso semanal (métricas para el admin,
    SOUL.md §3) — ya no bloquea la creación (uso interno de Canal 11 TVU).
    """
    if request.category not in _valid_categories(db):
        valid = ", ".join(_valid_categories(db)) or "ninguna configurada"
        raise HTTPException(status_code=400, detail=f"Categoría no válida. Opciones: {valid}")

    character = Character(
        user_id=current_user.id,
        name=request.name,
        category=request.category,
        status="active",
        reference_image_url=request.preview_image_url,
        generated_image_url=request.preview_image_url,
        heygen_avatar_id=request.avatar_id,
        heygen_avatar_group_id=request.avatar_group_id,
    )
    db.add(character)

    limits = get_or_create_character_limit(db, current_user.id)
    limits.characters_used += 1

    db.commit()
    db.refresh(character)
    return character


@router.get("", response_model=list[CharacterResponse])
def list_characters(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista los personajes del usuario actual."""
    return db.query(Character).filter(Character.user_id == current_user.id).all()


@router.get("/heygen-voices", response_model=list[HeygenVoice])
async def get_heygen_voices(current_user: User = Depends(get_current_user)):
    """Catálogo de voces en español de HeyGen para elegir la voz de un personaje."""
    return await list_spanish_voices()


@router.get("/voice-preview")
async def get_voice_preview(url: str):
    """Proxy del audio de preview de una voz de HeyGen (corrige el Content-Type,
    ver docstring de `fetch_voice_preview`). Sin auth a propósito: son clips
    públicos del catálogo de HeyGen, no datos del usuario — así el `<audio>`
    del frontend puede usar la URL directo, sin manejar el header de auth.
    """
    try:
        audio = await fetch_voice_preview(url)
    except ValueError:
        raise HTTPException(status_code=400, detail="URL de preview no válida")
    return Response(content=audio, media_type="audio/mpeg")


@router.patch("/{character_id}/voice", response_model=CharacterResponse)
def set_character_voice(
    character_id: str,
    request: CharacterVoiceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fija la voz de HeyGen del personaje — se reutiliza en todos sus spots
    (misma idea que reference_image_url: consistencia del personaje, SOUL.md §4).
    """
    character = db.query(Character).filter(
        Character.id == character_id,
        Character.user_id == current_user.id,
    ).first()
    if not character:
        raise HTTPException(status_code=404, detail="Personaje no encontrado")

    character.heygen_voice_id = request.voice_id
    character.heygen_voice_name = request.voice_name
    character.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(character)
    return character


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
