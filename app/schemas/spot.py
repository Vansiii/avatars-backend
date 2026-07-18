from datetime import datetime
from pydantic import BaseModel


class SpotCreateRequest(BaseModel):
    character_id: str
    script: str
    type: str  # "short" | "long"


class SpotVariation(BaseModel):
    index: int
    video_url: str


class SpotCreateResponse(BaseModel):
    spot_id: str
    variations: list[SpotVariation]
    redos_remaining: int
    estimated_seconds: int = 60


class SpotResponse(BaseModel):
    id: str
    character_id: str
    user_id: str
    script: str
    type: str
    status: str
    output_url: str | None
    duration_seconds: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SpotSelectRequest(BaseModel):
    variation_index: int


class SpotRedoResponse(BaseModel):
    spot_id: str
    variations: list[SpotVariation]
    redos_remaining: int
