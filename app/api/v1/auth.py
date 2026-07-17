from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.auth_handler import create_access_token, get_password_hash, verify_password
from app.auth.dependencies import get_current_user
from app.database.database import get_db
from app.models.models import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Nota: el CRUD de usuarios (crear/listar/eliminar) vive solo en api/v1/users.py.
# Antes estaba duplicado aquí y allá con la misma lógica — este router es
# exclusivamente sesión (login) y perfil propio (me).


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario inactivo")
    token = create_access_token(data={"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token)


@router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/users/me", response_model=UserResponse)
def update_me(
    request: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if request.display_name is not None:
        current_user.display_name = request.display_name
    if request.password is not None:
        current_user.hashed_password = get_password_hash(request.password)
    db.commit()
    db.refresh(current_user)
    return current_user
