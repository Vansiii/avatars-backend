from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin
from app.auth.auth_handler import get_password_hash
from app.database.database import get_db
from app.models.models import User
from app.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Lista todos los usuarios (solo admin)."""
    return db.query(User).all()


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    request: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Crea un nuevo usuario (solo admin)."""
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email")
    user = User(
        email=request.email,
        display_name=request.display_name,
        hashed_password=get_password_hash(request.password),
        role=request.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Obtiene un usuario por ID (solo admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Actualiza un usuario (solo admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if request.display_name is not None:
        user.display_name = request.display_name
    if request.password is not None:
        user.hashed_password = get_password_hash(request.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Elimina un usuario (solo admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="No se puede eliminar un administrador")
    db.delete(user)
    db.commit()
