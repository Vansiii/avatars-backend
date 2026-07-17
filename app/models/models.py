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
    reference_image_url = mapped_column(String(500), nullable=True)
    generated_image_url = mapped_column(String(500), nullable=True)
    category = mapped_column(String(20), nullable=False)
    status = mapped_column(String(10), nullable=False, default="draft")
    consistency_data = mapped_column(Text, nullable=True)
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
    output_url = mapped_column(String(500), nullable=True)
    duration_seconds = mapped_column(String(20), nullable=True)
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
