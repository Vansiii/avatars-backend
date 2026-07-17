from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./avatares.db"
    SECRET_KEY: str = "cambiar-esta-clave-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # APIs externas
    LUMA_API_KEY: str = ""
    POLLINATIONS_API_KEY: str = ""

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
