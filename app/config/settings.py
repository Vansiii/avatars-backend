from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./avatares.db"
    SECRET_KEY: str = "cambiar-esta-clave-en-produccion"
    ALGORITHM: str = "HS256"
    # SOUL.md §9.6: access corto + refresh de 7 días (antes solo había access de
    # 60 min sin refresh, así que una acción larga —p. ej. esperar un video de
    # HeyGen— podía deslogueártelo a mitad de camino).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # APIs externas
    LUMA_API_KEY: str = ""
    POLLINATIONS_API_KEY: str = ""
    SHOTSTACK_API_KEY_SANDBOX: str = ""
    SHOTSTACK_API_KEY_PRODUCTION: str = ""
    SHOTSTACK_ENV: str = "sandbox"
    HEYGEN_API_KEY: str = ""
    # Opcional: fuerza una voz específica. Si queda vacío, se auto-descubre la
    # primera voz en español del catálogo de HeyGen (ver video_provider.py).
    HEYGEN_VOICE_ID: str = ""
    # SOUL.md §5 pide 3 variaciones por spot; cada una es un video pago de
    # HeyGen. Configurable para poder bajarlo a 1 durante pruebas sin tocar
    # código ni el valor de negocio por defecto (ver .env para el override).
    HEYGEN_SPOT_VARIATIONS: int = 3

    # Límites semanales por defecto (SOUL.md §3) — el admin puede sobreescribirlos por usuario
    DEFAULT_CHARACTERS_LIMIT: int = 2
    DEFAULT_SPOTS_LIMIT: int = 5

    # Orígenes permitidos por CORS, separados por coma
    CORS_ORIGINS: str = "http://localhost:5173"

    model_config = {"env_file": ".env"}

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
