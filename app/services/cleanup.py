"""
Servicio de limpieza automática de archivos temporales.

Cumple con SOUL.md §5: privacidad de datos del usuario.
- Imágenes de entrada se eliminan a las 24 horas
- Avatares de usuarios free se eliminan a los 30 días
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models.generation import GenerationRequest, GeneratedAvatar
from app.media_paths import AVATARS_DIR


async def cleanup_input_images():
    """
    Elimina imágenes de entrada mayores a 24 horas.
    
    Nota: En el Alpha actual, las imágenes de entrada NO se guardan
    en disco (solo se procesan en memoria), así que esta función
    está preparada para cuando se implementen.
    
    SOUL.md §5: "La imagen de entrada se elimina a las 24 horas"
    """
    db = SessionLocal()
    try:
        # Buscar requests creados hace más de 24 horas
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        
        old_requests = db.query(GenerationRequest).filter(
            GenerationRequest.created_at < cutoff_time,
            GenerationRequest.input_image_url.isnot(None)
        ).all()
        
        deleted_count = 0
        for req in old_requests:
            if req.input_image_url and req.input_image_url.startswith("uploads/"):
                # Construir path y eliminar si existe
                # Nota: En Alpha no guardamos las imágenes de entrada todavía
                # Esta lógica está lista para cuando se implementen
                input_path = Path(f"app/media/{req.input_image_url}")
                if input_path.exists():
                    input_path.unlink()
                    deleted_count += 1
                
                # Limpiar referencia en DB
                req.input_image_url = None
        
        if deleted_count > 0:
            db.commit()
            print(f"[CLEANUP] Eliminadas {deleted_count} imágenes de entrada (>24h)")
        
    except Exception as e:
        print(f"[CLEANUP ERROR] Error al limpiar imágenes de entrada: {e}")
        db.rollback()
    finally:
        db.close()


async def cleanup_expired_avatars():
    """
    Elimina avatares de usuarios free que expiraron (>30 días).
    
    SOUL.md §2: Retención diferenciada:
    - free: 30 días
    - pro/enterprise: permanente
    """
    db = SessionLocal()
    try:
        # Buscar avatares con expires_at en el pasado
        now = datetime.now(timezone.utc)
        
        expired_avatars = db.query(GeneratedAvatar).filter(
            GeneratedAvatar.expires_at.isnot(None),
            GeneratedAvatar.expires_at < now
        ).all()
        
        deleted_count = 0
        for avatar in expired_avatars:
            # Eliminar archivo físico
            if avatar.storage_key:
                avatar_path = AVATARS_DIR / Path(avatar.storage_key).name
                if avatar_path.exists():
                    avatar_path.unlink()
                    deleted_count += 1
            
            # Eliminar registro de DB
            db.delete(avatar)
        
        if deleted_count > 0:
            db.commit()
            print(f"[CLEANUP] Eliminados {deleted_count} avatares expirados (free tier >30 días)")
        
    except Exception as e:
        print(f"[CLEANUP ERROR] Error al limpiar avatares expirados: {e}")
        db.rollback()
    finally:
        db.close()


async def run_cleanup_tasks():
    """
    Ejecuta todas las tareas de limpieza.
    
    Esta función debe ser llamada periódicamente, por ejemplo:
    - Cada hora con un cron job
    - Cada 6 horas con APScheduler
    - En el lifespan de FastAPI con un loop
    """
    print("[CLEANUP] Iniciando tareas de limpieza...")
    
    await cleanup_input_images()
    await cleanup_expired_avatars()
    
    print("[CLEANUP] Tareas de limpieza completadas")


async def cleanup_scheduler(interval_hours: int = 6):
    """
    Ejecuta tareas de limpieza cada N horas en background.
    
    Args:
        interval_hours: Intervalo entre ejecuciones (default: 6 horas)
    
    Uso en main.py:
        asyncio.create_task(cleanup_scheduler())
    """
    while True:
        try:
            await run_cleanup_tasks()
        except Exception as e:
            print(f"[CLEANUP ERROR] Error en scheduler: {e}")
        
        # Esperar hasta la próxima ejecución
        await asyncio.sleep(interval_hours * 3600)
