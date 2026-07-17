from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str


class CategoryUpdate(BaseModel):
    name: str | None = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    assigned_character_id: str | None = None

    model_config = {"from_attributes": True}
