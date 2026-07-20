import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name = mapped_column(String(255), nullable=False)
    hashed_password = mapped_column(String(255), nullable=False)
    role = mapped_column(String(10), nullable=False, default="user")
    is_active = mapped_column(Boolean, nullable=False, default=True)
    created_at = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    # Override de límites semanales por usuario (admin, SOUL.md §2). NULL = usa el default global.
    characters_limit_override = mapped_column(Integer, nullable=True)
    spots_limit_override = mapped_column(Integer, nullable=True)

    characters = relationship("Character", back_populates="user")
    spots = relationship("Spot", back_populates="user")
    character_limits = relationship("CharacterLimit", back_populates="user")


class Character(Base):
    __tablename__ = "characters"

    id = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    name = mapped_column(String(255), nullable=False)
    description = mapped_column(Text, nullable=True)
    # Text (no VARCHAR): las URLs firmadas de HeyGen (CloudFront, con
    # Signature/Key-Pair-Id) superan fácil los 500 caracteres.
    reference_image_url = mapped_column(Text, nullable=True)
    generated_image_url = mapped_column(Text, nullable=True)
    category = mapped_column(String(20), nullable=False)
    status = mapped_column(String(10), nullable=False, default="draft")
    consistency_data = mapped_column(Text, nullable=True)
    # Voz de HeyGen elegida para este personaje (misma voz en todos sus spots,
    # igual que reference_image_url — consistencia del personaje, SOUL.md §4).
    # NULL = video_provider auto-descubre una voz en español por defecto.
    heygen_voice_id = mapped_column(String(100), nullable=True)
    heygen_voice_name = mapped_column(String(255), nullable=True)
    # Identidad del personaje en HeyGen (foto propia animada o elegido del
    # catálogo público) — reemplaza a reference_image_url como fuente de
    # verdad para generar spots (SOUL.md §4). NULL en personajes creados
    # antes de este cambio, que siguen usando reference_image_url.
    heygen_avatar_id = mapped_column(String(100), nullable=True)
    heygen_avatar_group_id = mapped_column(String(100), nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="characters")
    spots = relationship("Spot", back_populates="character")


class Spot(Base):
    __tablename__ = "spots"

    id = mapped_column(String(36), primary_key=True, default=generate_uuid)
    character_id = mapped_column(String(36), ForeignKey("characters.id"), nullable=False)
    user_id = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    script = mapped_column(Text, nullable=False)
    type = mapped_column(String(10), nullable=False)
    status = mapped_column(String(10), nullable=False, default="pending")
    # Text (no VARCHAR): las URLs firmadas de HeyGen (CloudFront, con
    # Signature/Key-Pair-Id) superan fácil los 500 caracteres.
    output_url = mapped_column(Text, nullable=True)
    duration_seconds = mapped_column(String(20), nullable=True)
    # Variaciones en borrador antes de seleccionar (mismo patrón que Character.consistency_data)
    variations_data = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    character = relationship("Character", back_populates="spots")
    user = relationship("User", back_populates="spots")


class CharacterLimit(Base):
    __tablename__ = "character_limits"

    id = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    week_start = mapped_column(DateTime, nullable=False)
    characters_used = mapped_column(Integer, nullable=False, default=0)
    spots_used = mapped_column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="character_limits")


class SpotCategory(Base):
    __tablename__ = "spot_categories"

    id = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name = mapped_column(String(255), nullable=False, unique=True)
    assigned_character_id = mapped_column(String(36), ForeignKey("characters.id"), nullable=True)
