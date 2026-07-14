import uuid
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, File, Form, UploadFile, BackgroundTasks, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List, Optional, Dict
from app.database.database import get_db, SessionLocal
from app.models.user import User
from app.models.style import Style
from app.models.generation import GenerationRequest, GeneratedAvatar
from app.schemas.generation import GenerationSubmitResponse, HistoryItemResponse
from app.auth.dependencies import get_current_user
from app.media_paths import AVATARS_DIR
from app.services.image_provider import generate_image, NSFWRejected, ProviderError
from app.services.watermark import apply_watermark
from app.services.security_log import log_nsfw_rejection
from app.services.nsfw_filter import validate_image_content, ContentRejected, NSFWFilterError

router = APIRouter()

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, request_id: str, websocket: WebSocket):
        await websocket.accept()
        if request_id not in self.active_connections:
            self.active_connections[request_id] = []
        self.active_connections[request_id].append(websocket)

    def disconnect(self, request_id: str, websocket: WebSocket):
        if request_id in self.active_connections:
            self.active_connections[request_id].remove(websocket)
            if not self.active_connections[request_id]:
                del self.active_connections[request_id]

    async def broadcast(self, request_id: str, message: dict):
        if request_id in self.active_connections:
            for connection in self.active_connections[request_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()

# Background Generation Task
async def generate_avatar_background(request_id: uuid.UUID):
    import time
    start_time = time.time()
    
    db = SessionLocal()
    try:
        req = db.query(GenerationRequest).filter(GenerationRequest.id == request_id).first()
        if not req:
            return

        req.status = "processing"
        db.commit()

        style = db.query(Style).filter(Style.id == req.style_id).first()
        
        # Construcción del prompt: El prompt del usuario va PRIMERO para mayor control
        # El base_prompt del estilo sirve como modificador de estilo al final
        if req.prompt and style and style.base_prompt:
            # Usuario especificó algo: su descripción + estilo aplicado
            full_prompt = f"{req.prompt}, {style.base_prompt}"
        elif req.prompt:
            # Solo prompt de usuario, sin estilo
            full_prompt = req.prompt
        elif style and style.base_prompt:
            # Solo estilo, sin descripción (ej: subió foto sin texto)
            full_prompt = style.base_prompt
        else:
            # Fallback por seguridad
            full_prompt = "professional portrait avatar, studio lighting"
        # NOTA: en este Alpha la foto subida por el usuario NO condiciona la generación
        # todavía (Pollinations "kontext" para imagen->imagen requiere una URL pública
        # del archivo de entrada, y aún no hay storage público). Si solo se subió una
        # foto sin prompt, se genera un avatar del estilo elegido, no personalizado.

        # Paso 1: validar entrada (20%). El filtro NSFW de Pollinations (safe=true)
        # se aplica dentro de la misma llamada de generación, no como paso separado.
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 20,
                "message": "Validando entrada..."
            }
        })

        # Paso 2: generar variaciones con IA (50%)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 50,
                "message": "Generando avatar con IA..."
            }
        })

        try:
            tasks = [generate_image(full_prompt) for _ in range(req.variations)]
            raw_images = await asyncio.gather(*tasks)
        except NSFWRejected as exc:
            log_nsfw_rejection(req.user_id, "prompt" if req.prompt else "file", str(exc))
            req.status = "failed"
            db.commit()
            await manager.broadcast(str(request_id), {
                "event": "generation_failed",
                "data": {
                    "request_id": str(request_id),
                    "status": "failed",
                    "error_code": "GEN_004",
                    "message": "El contenido solicitado no cumple con nuestras políticas de uso."
                }
            })
            return
        except ProviderError:
            req.status = "failed"
            db.commit()
            await manager.broadcast(str(request_id), {
                "event": "generation_failed",
                "data": {
                    "request_id": str(request_id),
                    "status": "failed",
                    "message": "El proveedor de IA no respondió. Intenta nuevamente."
                }
            })
            return

        # Paso 3: validar contenido de salida (filtro NSFW obligatorio, SOUL.md §4)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 70,
                "message": "Validando contenido generado..."
            }
        })

        # Validar todas las imágenes generadas
        try:
            for i, image_bytes in enumerate(raw_images):
                validate_image_content(image_bytes, threshold=0.6, mode="moderate")
        except (ContentRejected, NSFWFilterError) as exc:
            # SOUL.md §4: contenido rechazado → GEN_004, sin cobrar crédito
            log_nsfw_rejection(req.user_id, "generated_output", str(exc))
            req.status = "failed"
            db.commit()
            await manager.broadcast(str(request_id), {
                "event": "generation_failed",
                "data": {
                    "request_id": str(request_id),
                    "status": "failed",
                    "error_code": "GEN_004",
                    "message": "El contenido generado no cumple con nuestras políticas de uso."
                }
            })
            return

        # Paso 4: watermark + guardado (80%)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 80,
                "message": "Aplicando marca de agua y optimizando..."
            }
        })

        avatars = []
        for i, image_bytes in enumerate(raw_images):
            watermarked = apply_watermark(image_bytes)
            filename = f"{request_id}_{i}.png"
            (AVATARS_DIR / filename).write_bytes(watermarked)

            avatar = GeneratedAvatar(
                id=uuid.uuid4(),
                request_id=request_id,
                storage_key=f"avatars/{filename}",
                cdn_url=f"/media/avatars/{filename}",
                resolution="512x512",
                is_watermarked=True,
                is_premium=False
            )
            db.add(avatar)
            avatars.append(avatar)

        req.status = "completed"
        req.completed_at = func.now()

        # Deduct credit — solo se cobra si la generación se completó
        user = db.query(User).filter(User.id == req.user_id).first()
        if user:
            user.credits_used += 1

        db.commit()

        # Medir latencia total (B-08)
        elapsed_time = time.time() - start_time
        print(f"[METRICS] Generación completada en {elapsed_time:.2f}s para {req.variations} variaciones (request_id: {request_id})")

        # Broadcast completed
        avatars_response = [
            {
                "id": str(a.id),
                "preview_url": a.cdn_url,
                "download_url": a.cdn_url,
                "resolution": a.resolution,
                "is_watermarked": a.is_watermarked
            } for a in avatars
        ]

        await manager.broadcast(str(request_id), {
            "event": "generation_completed",
            "data": {
                "request_id": str(request_id),
                "status": "completed",
                "avatars": avatars_response,
                "credits_remaining": user.credits_limit - user.credits_used if user else 0
            }
        })

    except Exception as e:
        print(f"[ERROR] Error in background generation: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        try:
            req = db.query(GenerationRequest).filter(GenerationRequest.id == request_id).first()
            if req:
                req.status = "failed"
                db.commit()
            await manager.broadcast(str(request_id), {
                "event": "generation_failed",
                "data": {
                    "request_id": str(request_id),
                    "status": "failed",
                    "message": "Error al generar el avatar."
                }
            })
        except Exception as broadcast_error:
            print(f"[ERROR] Failed to broadcast error: {broadcast_error}")
    finally:
        db.close()

@router.post("/generations", response_model=GenerationSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_generation(
    background_tasks: BackgroundTasks,
    style_id: uuid.UUID = Form(...),
    prompt: Optional[str] = Form(None),
    variations: int = Form(3),
    notes: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate Credits
    if current_user.credits_used >= current_user.credits_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Has alcanzado tu límite mensual de créditos. Por favor actualiza tu plan.",
            headers={"x-error-code": "GEN_003"}
        )
        
    # Validate Inputs: must have either file or prompt
    if not file and not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar una imagen o una descripción textual."
        )
        
    # Validate File
    if file:
        if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El archivo debe ser JPEG, PNG o WEBP.",
                headers={"x-error-code": "GEN_001"}
            )
        # Check size (max 10MB)
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La imagen no puede pesar más de 10 MB.",
                headers={"x-error-code": "GEN_002"}
            )
        
        # Strip EXIF metadata for privacy (SOUL.md §5)
        try:
            from app.services.nsfw_filter import strip_image_metadata
            file_bytes = file.file.read()
            file_bytes_clean = strip_image_metadata(file_bytes)
            file.file.seek(0)  # Reset for potential later use
            # Note: We've cleaned the data but the original file object is still used
            # This is acceptable for Alpha as we don't persist the input image yet
        except Exception as e:
            print(f"[WARNING] Failed to strip EXIF metadata: {e}")
            # Continue anyway - EXIF stripping is best-effort in Alpha

            
    # Validate Prompt
    if prompt:
        if len(prompt) < 10 or len(prompt) > 500:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La descripción debe tener entre 10 y 500 caracteres."
            )

    # Validate Style
    style = db.query(Style).filter(Style.id == style_id, Style.is_active == True).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estilo no encontrado o inactivo."
        )
        
    # Check if user has sufficient plan tier for style
    # If style is 'pro' and user is 'free', block
    if style.tier_required == "pro" and current_user.plan_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este estilo requiere un plan Pro o superior."
        )
    elif style.tier_required == "enterprise" and current_user.plan_tier != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este estilo requiere un plan Enterprise."
        )

    # Validate Variations
    if variations < 3 or variations > 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cantidad de variaciones debe ser entre 3 y 6."
        )

    # Create Generation Request Record
    req_id = uuid.uuid4()
    req = GenerationRequest(
        id=req_id,
        user_id=current_user.id,
        style_id=style_id,
        prompt=prompt,
        input_image_url="uploads/mock_input.png" if file else None,
        status="pending",
        variations=variations,
        notes=notes
    )
    db.add(req)
    db.commit()
    
    # Enqueue Background Task
    background_tasks.add_task(generate_avatar_background, req_id)
    
    return {
        "status": "pending",
        "data": {
            "request_id": req_id,
            "estimated_seconds": 15,
            "websocket_channel": f"/api/v1/ws/generations/{req_id}"
        }
    }

@router.get("/users/me/history", response_model=List[HistoryItemResponse])
def get_user_history(
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Pagination
    offset = (page - 1) * limit
    
    # Get requests and join with Style
    requests = db.query(GenerationRequest).filter(
        GenerationRequest.user_id == current_user.id
    ).order_by(
        GenerationRequest.created_at.desc()
    ).offset(offset).limit(limit).all()
    
    history_items = []
    for r in requests:
        style_name = r.style.name if r.style else None
        style_category = r.style.category if r.style else None
        
        avatars = []
        for a in r.avatars:
            avatars.append({
                "id": a.id,
                "preview_url": a.cdn_url,
                "download_url": a.cdn_url,
                "resolution": a.resolution,
                "is_watermarked": a.is_watermarked
            })
            
        history_items.append({
            "id": r.id,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
            "style_name": style_name,
            "style_category": style_category,
            "prompt": r.prompt,
            "status": r.status,
            "avatars": avatars
        })
        
    return history_items

@router.websocket("/ws/generations/{request_id}")
async def websocket_endpoint(websocket: WebSocket, request_id: str):
    await manager.connect(request_id, websocket)
    try:
        # Keep connection open and listen for messages (if client sends any)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(request_id, websocket)
