from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from app.database.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, UserUpdate, UserResponse, Token
from app.auth.auth_handler import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.auth.dependencies import get_current_user
import re

router = APIRouter()

class RefreshTokenRequest(BaseModel):
    refresh_token: str

@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # Password strength check
    password = user_in.password
    if len(password) < 8 or not any(c.isupper() for c in password) or not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña debe tener al menos 8 caracteres, una mayúscula y un número."
        )

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        # AC-001: Clear error but without revealing if the account exists.
        # We return a 201/200 generic message so as not to leak account existence, OR a standard warning.
        # To avoid enumeration, we simulate a successful registration message.
        return {"message": "Si el correo es válido, se enviará un enlace de confirmación."}

    # Create new user
    new_user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        plan_tier="free",
        credits_used=0,
        credits_limit=5,
        is_active=True,
        is_verified=False  # True when verification flow is complete
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": "Si el correo es válido, se enviará un enlace de confirmación."}

@router.post("/auth/login", response_model=Token)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_in.email).first()
    
    # Check password
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cuenta inactiva"
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/auth/refresh", response_model=Token)
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_data = decode_token(payload.refresh_token)
    if not token_data or token_data.get("refresh") is not True:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de actualización inválido"
        )
        
    user_id = token_data.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de actualización inválido"
        )
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o inexistente"
        )
        
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.post("/auth/logout")
def logout():
    # Stateless JWT logout: client discards the token.
    return {"message": "Sesión cerrada correctamente"}

# Profile endpoints under /users/me
@router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/users/me", response_model=UserResponse)
def update_me(user_update: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_update.display_name is not None:
        current_user.display_name = user_update.display_name
    if user_update.bio is not None:
        current_user.bio = user_update.bio
    if user_update.avatar_url is not None:
        current_user.avatar_url = user_update.avatar_url
        
    db.commit()
    db.refresh(current_user)
    return current_user

@router.delete("/users/me", status_code=status.HTTP_200_OK)
def delete_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # AC-005: Account deletion. Removes all user data.
    # In production, we'd also trigger background jobs to delete S3 assets.
    db.delete(current_user)
    db.commit()
    return {"message": "Cuenta eliminada permanentemente"}
