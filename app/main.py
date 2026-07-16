import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.database.database import engine, Base, SessionLocal
from app.database.seeding import seed_styles
from app.logging_config import configure_logging
from app.media_paths import MEDIA_ROOT
from app.middleware.degraded import enter_degraded, recover_redis
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
from app.models.session import Session  # noqa: E402
from app.models.refresh_token import RefreshToken  # noqa: E402

# Import API routers
from app.api.v1.auth import router as auth_router  # noqa: E402
from app.api.v1.styles import router as styles_router  # noqa: E402
from app.api.v1.generations import router as generations_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    try:
        with engine.connect():
            pass
        logger.info("Database connection verified")
    except Exception as exc:
        logger.critical("Database connection failed", extra={"error": str(exc)})
        sys.exit(1)

    app.state.redis = None
    app.state.degraded = False
    try:
        redis_client = await create_redis_pool(
            settings.REDIS_URL,
            connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
        )
        set_redis(redis_client)
        app.state.redis = redis_client
        logger.info("Redis connection established")
    except RedisUnavailable:
        enter_degraded(app, reason="redis startup unavailable")

    async def recover_redis_loop() -> None:
        while True:
            await asyncio.sleep(30)
            if not app.state.degraded:
                continue
            try:
                await close_redis()
                candidate = await create_redis_pool(
                    settings.REDIS_URL,
                    connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
                )
                if await recover_redis(app, candidate):
                    set_redis(candidate)
                else:
                    await candidate.aclose()
            except Exception:
                # Recovery remains best-effort; the shared helper preserves degraded state.
                continue

    db = SessionLocal()
    try:
        seed_styles(db)
    finally:
        db.close()

    cleanup_task = asyncio.create_task(cleanup_scheduler(interval_hours=6))
    recovery_task = asyncio.create_task(recover_redis_loop())
    logger.info("Background cleanup and Redis recovery schedulers started")

    try:
        yield
    finally:
        cleanup_task.cancel()
        recovery_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        with suppress(asyncio.CancelledError):
            await recovery_task
        await close_redis()
        logger.info("Shutdown complete")


app = FastAPI(
    title="ProyectoIA API",
    description="API para gestión de identidades digitales y avatares con IA",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware stack (the last registration executes outermost) ──

# Rate limiting is closest to the router so outer security middleware decorates 429s.
app.add_middleware(
    RateLimitMiddleware,
    general_per_minute=settings.RATE_LIMIT_GENERAL_PER_MINUTE,
    generation_per_minute=settings.RATE_LIMIT_GENERATION_PER_MINUTE,
)

# Security headers and request context also cover rate-limit rejections.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

# CORS is outermost so preflight remains available before API middleware.
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
