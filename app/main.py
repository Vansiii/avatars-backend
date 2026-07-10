from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.database.database import engine, Base, SessionLocal
from app.database.seeding import seed_styles

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
    # 1. Create database tables if they do not exist
    Base.metadata.create_all(bind=engine)
    
    # 2. Seed initial styles catalog
    db = SessionLocal()
    try:
        seed_styles(db)
    finally:
        db.close()
        
    yield

app = FastAPI(
    title="ProyectoIA API",
    description="API para gestión de identidades digitales y avatares con IA",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Modify for production to restrict allowed domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers under prefix /api/v1
app.include_router(auth_router, prefix="/api/v1")
app.include_router(styles_router, prefix="/api/v1")
app.include_router(generations_router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API de ProyectoIA. La base de datos está conectada y los servicios de catálogo de estilos y generación de avatares están listos."}
