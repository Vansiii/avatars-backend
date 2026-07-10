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
    await asyncio.sleep(1) # delay start
    db = SessionLocal()
    try:
        req = db.query(GenerationRequest).filter(GenerationRequest.id == request_id).first()
        if not req:
            return
            
        req.status = "processing"
        db.commit()
        
        # Step 1: Validate input (20% progress)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 20,
                "message": "Validando entrada..."
            }
        })
        await asyncio.sleep(2)
        
        # Step 2: Apply style (50% progress)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 50,
                "message": "Aplicando estilo visual..."
            }
        })
        await asyncio.sleep(2.5)
        
        # Step 3: Upscaling & Watermarking (80% progress)
        await manager.broadcast(str(request_id), {
            "event": "generation_progress",
            "data": {
                "request_id": str(request_id),
                "status": "processing",
                "progress": 80,
                "message": "Optimizando imagen y escalando..."
            }
        })
        await asyncio.sleep(2)
        
        style = db.query(Style).filter(Style.id == req.style_id).first()
        category = style.category if style else "professional"
        
        # Curated Unsplash images that represent high-quality avatares
        placeholders = {
            "professional": [
                "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=512&h=512&fit=crop"
            ],
            "gaming": [
                "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1566492031773-4f4e44671857?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=512&h=512&fit=crop"
            ],
            "social": [
                "https://images.unsplash.com/photo-1614680376593-902f74fa0d41?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=512&h=512&fit=crop"
            ],
            "gaming-character": [
                "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1518770660439-4636190af475?w=512&h=512&fit=crop",
                "https://images.unsplash.com/photo-1509248961158-e54f6934749c?w=512&h=512&fit=crop"
            ]
        }
        
        urls = placeholders.get(category, placeholders["professional"])
        
        avatars = []
        for i in range(req.variations):
            url = urls[i % len(urls)]
            avatar_url = f"{url}&sig={request_id}_{i}"
            avatar = GeneratedAvatar(
                id=uuid.uuid4(),
                request_id=request_id,
                storage_key=f"avatars/{request_id}_{i}.png",
                cdn_url=avatar_url,
                resolution="512x512",
                is_watermarked=True,
                is_premium=False
            )
            db.add(avatar)
            avatars.append(avatar)
            
        req.status = "completed"
        req.completed_at = func.now()
        
        # Deduct credit
        user = db.query(User).filter(User.id == req.user_id).first()
        if user:
            user.credits_used += 1
            
        db.commit()
        
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
        print("Error in background generation:", e)
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
        except Exception:
            pass
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
