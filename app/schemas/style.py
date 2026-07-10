from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

class StyleBase(BaseModel):
    name: str
    slug: str
    category: str
    description: Optional[str] = None
    preview_url: Optional[str] = None
    example_urls: List[str] = Field(default_factory=list)
    tier_required: str = "free"  # 'free', 'pro', 'enterprise'
    tags: List[str] = Field(default_factory=list)
    sort_order: int = 0

class StyleCreate(StyleBase):
    base_prompt: Optional[str] = None

class StyleUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    example_urls: Optional[List[str]] = None
    base_prompt: Optional[str] = None
    is_active: Optional[bool] = None
    tier_required: Optional[str] = None
    tags: Optional[List[str]] = None
    sort_order: Optional[int] = None

class StyleResponse(StyleBase):
    id: UUID
    is_active: bool

    class Config:
        from_attributes = True
