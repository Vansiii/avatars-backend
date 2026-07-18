from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.database.database import Base, engine
from app.database.seeding import seed_default_categories
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.users import router as users_router
from app.api.v1.categories import router as categories_router
from app.api.v1.characters import router as characters_router
from app.api.v1.spots import router as spots_router

# Crear tablas al arrancar (Alpha — en producción usar Alembic)
Base.metadata.create_all(bind=engine)
seed_default_categories()

app = FastAPI(
    title="Avatares API",
    description="Sistema de Personajes para Spots Publicitarios de TV",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(categories_router)
app.include_router(characters_router)
app.include_router(spots_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
