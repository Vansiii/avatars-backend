import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.database.database import engine, Base, SessionLocal
from app.database.seeding import seed_styles
from app.logging_config import configure_logging
from app.media_paths import MEDIA_ROOT
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services.cleanup import cleanup_scheduler
from app.services.redis_client import (
    RedisUnavailable,
    close_redis,
    create_redis_pool,
    set_redis,
)

# Configure JSON logging FIRST
configure_logging()

logger = logging.getLogger(__name__)


# Import models to ensure they are registered with SQLAlchemy Base metadata
from app.models.user import User  # noqa: E402
from app.models.style import Style  # noqa: E402
from app.models.generation import GenerationRequest, GeneratedAvatar  # noqa: E402

# Import API routers
from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.styles import router as styles_router  # noqa: E402
from app.api.v1.generations import router as generations_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──

    # 1. Verify database connectivity (Alembic manages schema)
    try:
        with engine.connect():
            pass
        logger.info("Database connection verified")
    except Exception as exc:
        logger.critical("Database connection failed", extra={"error": str(exc)})
        sys.exit(1)

    # 2. Verify Alembic migration state

    # 3. Initialize Redis connection
    try:
        redis_client = await create_redis_pool(
            settings.REDIS_URL,
            connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
        )
        set_redis(redis_client)
        logger.info("Redis connection established")
    except RedisUnavailable as exc:
        logger.critical("Redis unavailable, shutting down", extra={"error": str(exc)})
        sys.exit(1)

    # 4. Seed initial styles catalog
    db = SessionLocal()
    try:
        seed_styles(db)
    finally:
        db.close()

    # 5. Start background cleanup scheduler
    cleanup_task = asyncio.create_task(cleanup_scheduler(interval_hours=6))
    logger.info("Background cleanup scheduler started (every 6 hours)")

    yield

    # ── Shutdown ──
    cleanup_task.cancel()
    await close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title="ProyectoIA API",
    description="API para gestión de identidades digitales y avatares con IA",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware stack (execution order: outermost first) ──

# CORS (outermost, handles preflight before other middlewares)
_dev_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
_extra_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_dev_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# Request context (request ID, contextvars)
app.add_middleware(RequestContextMiddleware)

# Rate limiting (closest to router)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.RATE_LIMIT_GENERAL_PER_MINUTE,
    generation_requests_per_minute=settings.RATE_LIMIT_GENERATION_PER_MINUTE,
)

# ── Routes ──
app.include_router(auth_router, prefix="/api/v1")
app.include_router(styles_router, prefix="/api/v1")
app.include_router(generations_router, prefix="/api/v1")

# Static files for generated avatars
app.mount("/media", StaticFiles(directory=str(MEDIA_ROOT)), name="media")


@app.get("/")
def read_root():
    return {
        "message": (
            "Bienvenido a la API de ProyectoIA. "
            "La base de datos está conectada y los servicios "
            "de catálogo de estilos y generación de avatares están listos."
        )
    }


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "ok", "version": "1.0.0"}
