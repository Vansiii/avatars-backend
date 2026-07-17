from datetime import datetime
from pydantic import BaseModel


class CharacterCreate(BaseModel):
    name: str
    description: str | None = None
    category: str
    # Imagen de referencia opcional (se subirá como archivo)
    # prompt de texto opcional


class CharacterVariation(BaseModel):
    index: int
    image_url: str


class CharacterResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: str | None
    reference_image_url: str | None
    generated_image_url: str | None
    category: str
    status: str
    consistency_data: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterSelectRequest(BaseModel):
    variation_index: int


class CharacterRedoResponse(BaseModel):
    character_id: str
    variations: list[CharacterVariation]
    redos_remaining: int


class CharacterCreateResponse(BaseModel):
    character_id: str
    variations: list[CharacterVariation]
    redos_remaining: int
    estimated_seconds: int = 30
