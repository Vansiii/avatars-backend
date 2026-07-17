from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.database.database import get_db
from app.models.models import SpotCategory, User
from app.schemas.categories import CategoryCreate, CategoryResponse, CategoryUpdate

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    """Lista todas las categorías disponibles."""
    return db.query(SpotCategory).all()


@router.post("", response_model=CategoryResponse, status_code=201)
def create_category(
    request: CategoryCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Crea una nueva categoría de spots (solo admin)."""
    existing = db.query(SpotCategory).filter(SpotCategory.name == request.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
    category = SpotCategory(name=request.name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: str,
    request: CategoryUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Actualiza una categoría (solo admin)."""
    category = db.query(SpotCategory).filter(SpotCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    if request.name is not None:
        existing = db.query(SpotCategory).filter(
            SpotCategory.name == request.name,
            SpotCategory.id != category_id,
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Ya existe una categoría con ese nombre")
        category.name = request.name
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Elimina una categoría (solo admin)."""
    category = db.query(SpotCategory).filter(SpotCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoría no encontrada")
    db.delete(category)
    db.commit()
