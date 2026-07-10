import uuid
from sqlalchemy import Column, String, Boolean, Integer, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.database.database import Base

class Style(Base):
    __tablename__ = "styles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    category = Column(String(100), nullable=False)  # 'professional', 'gaming', 'corporate', 'social', etc.
    description = Column(Text, nullable=True)
    preview_url = Column(String, nullable=True)
    example_urls = Column(JSON, default=list, nullable=False)  # List of strings
    base_prompt = Column(Text, nullable=True)  # Base prompt template for AI generation
    is_active = Column(Boolean, default=True, nullable=False)
    tier_required = Column(String(50), default="free", nullable=False)  # 'free', 'pro', 'enterprise'
    tags = Column(JSON, default=list, nullable=False)  # List of tag strings
    sort_order = Column(Integer, default=0, nullable=False)
