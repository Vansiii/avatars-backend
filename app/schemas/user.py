from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    display_name: str
    password: str
    role: str = "user"


class UserUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
