from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime

class GeneratedAvatarSchema(BaseModel):
    id: UUID
    storage_key: str
    cdn_url: str
    resolution: str
    is_watermarked: bool
    is_premium: bool
    created_at: datetime

    class Config:
        from_attributes = True

class GenerationResponseDetail(BaseModel):
    request_id: UUID
    estimated_seconds: int
    websocket_channel: str

class GenerationSubmitResponse(BaseModel):
    status: str
    data: GenerationResponseDetail

class HistoryAvatarResponse(BaseModel):
    id: UUID
    preview_url: str
    download_url: str
    resolution: str
    is_watermarked: bool

class HistoryItemResponse(BaseModel):
    id: UUID
    created_at: datetime
    completed_at: Optional[datetime] = None
    style_name: Optional[str] = None
    style_category: Optional[str] = None
    prompt: Optional[str] = None
    status: str
    avatars: List[HistoryAvatarResponse] = []

    class Config:
        from_attributes = True
