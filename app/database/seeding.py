"""Script para crear el usuario admin inicial.

Ejecutar una vez:
    cd backend
    python -m app.database.seeding
"""

from app.database.database import SessionLocal
from app.models.models import User
from app.auth.auth_handler import get_password_hash


def create_admin():
    db = SessionLocal()
    try:
        # Verificar si ya existe un admin
        existing = db.query(User).filter(User.role == "admin").first()
        if existing:
            print(f"Ya existe un admin: {existing.email}")
            return

        admin = User(
            email="admin@avatares.com",
            display_name="Administrador",
            hashed_password=get_password_hash("admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"Admin creado: {admin.email} / admin123")
        print("IMPORTANTE: Cambia la contraseña después del primer login.")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
