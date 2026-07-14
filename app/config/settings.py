# Configuración del entorno
import os
import sys
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "ProyectoIA"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/proyectoia")
    
    # JWT Auth
    # SECURITY: SECRET_KEY must be set in .env file
    # No default value for production safety (SOUL.md §5)
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Proveedor de IA (Pollinations.ai)
    POLLINATIONS_API_KEY: str = os.getenv("POLLINATIONS_API_KEY", "")
    
    # Cloudinary (para storage de imágenes de entrada)
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    class Config:
        env_file = ".env"
        case_sensitive = False
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Validate critical settings on startup
        if not self.SECRET_KEY:
            print("\n" + "="*70)
            print("ERROR: SECRET_KEY no está configurado en las variables de entorno")
            print("="*70)
            print("Por favor, agrega SECRET_KEY a tu archivo .env")
            print("Ejemplo: SECRET_KEY=tu-clave-secreta-super-segura-aqui")
            print("="*70 + "\n")
            sys.exit(1)
        
        if self.SECRET_KEY == "super-secret-key-change-in-production":
            print("\n" + "="*70)
            print("WARNING: Usando SECRET_KEY inseguro por defecto")
            print("="*70)
            print("Por favor, cambia SECRET_KEY en tu archivo .env")
            print("="*70 + "\n")

settings = Settings()
