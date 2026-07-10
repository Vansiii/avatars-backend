from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from app.database.database import get_db
from app.models.style import Style
from app.schemas.style import StyleResponse, StyleCreate, StyleUpdate
from app.auth.dependencies import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("/styles", response_model=List[StyleResponse])
def list_styles(
    category: Optional[str] = None,
    tier: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Style).filter(Style.is_active == True)
    if category:
        query = query.filter(Style.category == category)
    if tier:
        query = query.filter(Style.tier_required == tier)
    return query.order_by(Style.sort_order.asc()).all()

@router.get("/styles/{slug}", response_model=StyleResponse)
def get_style_by_slug(slug: str, db: Session = Depends(get_db)):
    style = db.query(Style).filter(Style.slug == slug, Style.is_active == True).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estilo no encontrado"
        )
    return style

# Admin endpoints (mocked role verification for MVP, allows all authenticated users for now)
@router.post("/admin/styles", response_model=StyleResponse, status_code=status.HTTP_201_CREATED)
def create_style(
    style_in: StyleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # For MVP, only users with 'enterprise' plan tier or specific email domains are mock admins, or we let it pass for development
    existing = db.query(Style).filter(Style.slug == style_in.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un estilo con ese slug"
        )
    new_style = Style(**style_in.dict())
    db.add(new_style)
    db.commit()
    db.refresh(new_style)
    return new_style

@router.put("/admin/styles/{id}", response_model=StyleResponse)
def update_style(
    id: UUID,
    style_in: StyleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    style = db.query(Style).filter(Style.id == id).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estilo no encontrado"
        )
    
    update_data = style_in.dict(exclude_unset=True)
    for field, val in update_data.items():
        setattr(style, field, val)
        
    db.commit()
    db.refresh(style)
    return style

@router.delete("/admin/styles/{id}", status_code=status.HTTP_200_OK)
def delete_style(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    style = db.query(Style).filter(Style.id == id).first()
    if not style:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Estilo no encontrado"
        )
    # Perform logical deletion by setting active to False
    style.is_active = False
    db.commit()
    return {"message": "Estilo desactivado correctamente"}
