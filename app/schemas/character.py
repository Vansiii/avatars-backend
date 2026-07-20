from datetime import datetime
from pydantic import BaseModel


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
    heygen_voice_id: str | None
    heygen_voice_name: str | None
    heygen_avatar_id: str | None
    heygen_avatar_group_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterVoiceRequest(BaseModel):
    voice_id: str
    voice_name: str


class HeygenVoice(BaseModel):
    voice_id: str
    name: str
    gender: str | None = None
    preview_audio_url: str | None = None


class CharacterFromPhotoResponse(BaseModel):
    avatar_id: str
    avatar_group_id: str
    preview_image_url: str


class HeygenCatalogAvatar(BaseModel):
    avatar_id: str
    avatar_group_id: str
    name: str
    preview_image_url: str | None = None
    gender: str | None = None


class HeygenCatalogResponse(BaseModel):
    items: list[HeygenCatalogAvatar]
    next_token: str | None = None


class CharacterConfirmRequest(BaseModel):
    name: str
    category: str
    avatar_id: str
    avatar_group_id: str
    preview_image_url: str
