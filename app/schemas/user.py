from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="La contraseña debe tener al menos 8 caracteres")

class UserLogin(UserBase):
    password: str

class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=200)
    avatar_url: Optional[str] = None

class UserResponse(UserBase):
    id: UUID
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    plan_tier: str
    credits_used: int
    credits_limit: int
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None
