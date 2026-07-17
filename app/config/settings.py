from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./avatares.db"
    SECRET_KEY: str = "cambiar-esta-clave-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # APIs externas
    LUMA_API_KEY: str = ""
    POLLINATIONS_API_KEY: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
