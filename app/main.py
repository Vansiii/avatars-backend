from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio

from app.database.database import engine, Base, SessionLocal
from app.database.seeding import seed_styles
from app.media_paths import MEDIA_ROOT
from app.services.cleanup import cleanup_scheduler
from app.middleware.rate_limit import RateLimitMiddleware

# Import models to ensure they are registered with SQLAlchemy Base metadata
from app.models.user import User
from app.models.style import Style
from app.models.generation import GenerationRequest, GeneratedAvatar

# Import API routers
from app.api.v1.auth import router as auth_router
from app.api.v1.styles import router as styles_router
from app.api.v1.generations import router as generations_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # 1. Create database tables if they do not exist
    Base.metadata.create_all(bind=engine)
    
    # 2. Seed initial styles catalog
    db = SessionLocal()
    try:
        seed_styles(db)
    finally:
        db.close()
    
    # 3. Start background cleanup scheduler (runs every 6 hours)
    cleanup_task = asyncio.create_task(cleanup_scheduler(interval_hours=6))
    print("[STARTUP] Background cleanup scheduler iniciado (cada 6 horas)")
        
    yield
    
    # Shutdown
    cleanup_task.cancel()
    print("[SHUTDOWN] Background cleanup scheduler detenido")

app = FastAPI(
    title="ProyectoIA API",
    description="API para gestión de identidades digitales y avatares con IA",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
# SECURITY: In production, restrict to specific domains
# For Alpha development, allowing localhost origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],  # Frontend dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting Middleware
# Protects against abuse and DoS attacks (SOUL.md §5)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=100,  # Límite general por IP/usuario
    generation_requests_per_minute=20  # Límite específico para generaciones
)

# Register routers under prefix /api/v1
app.include_router(auth_router, prefix="/api/v1")
app.include_router(styles_router, prefix="/api/v1")
app.include_router(generations_router, prefix="/api/v1")

# Avatares generados: servidos localmente (sin S3/CDN en el Alpha)
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API de ProyectoIA. La base de datos está conectada y los servicios de catálogo de estilos y generación de avatares están listos."}
