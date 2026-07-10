from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import Optional
from app.database.database import get_db
from app.models.user import User
from app.auth.auth_handler import decode_token

# Token URL corresponds to the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Inicie sesión para acceder a este recurso",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
        
    payload = decode_token(token)
    if payload is None or payload.get("refresh") is True:
        raise credentials_exception
        
    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception
        
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
        
    return user
