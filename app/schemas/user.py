from pydantic import BaseModel

class UserSchema(BaseModel):
    id: int
    email: str
    is_active: bool

    class Config:
        from_attributes = True
