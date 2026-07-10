import uuid
from sqlalchemy import Column, String, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.database import Base

class GenerationRequest(Base):
    __tablename__ = "generation_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    style_id = Column(UUID(as_uuid=True), ForeignKey("styles.id", ondelete="SET NULL"), nullable=True)
    
    prompt = Column(Text, nullable=True)
    input_image_url = Column(String, nullable=True)
    status = Column(String(50), default="pending", nullable=False)  # 'pending', 'processing', 'completed', 'failed'
    job_id = Column(String(255), nullable=True)  # Celery job ID or external api job ID
    variations = Column(Integer, default=3, nullable=False)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", backref="generation_requests")
    style = relationship("Style", backref="generation_requests")
    avatars = relationship("GeneratedAvatar", back_populates="request", cascade="all, delete-orphan")

class GeneratedAvatar(Base):
    __tablename__ = "generated_avatars"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("generation_requests.id", ondelete="CASCADE"), nullable=False)
    
    storage_key = Column(String, nullable=False)  # S3/GCS object key
    cdn_url = Column(String, nullable=False)  # Accessible public/signed URL
    resolution = Column(String(20), default="512x512", nullable=False)  # e.g. '512x512', '1024x1024'
    is_watermarked = Column(Boolean, default=True, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Null if permanent
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    request = relationship("GenerationRequest", back_populates="avatars")
