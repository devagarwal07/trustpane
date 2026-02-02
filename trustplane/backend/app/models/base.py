"""
Base models and mixins
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel as PydanticBaseModel, Field
from uuid import UUID, uuid4


class BaseModel(PydanticBaseModel):
    """Base model with common configuration"""
    
    class Config:
        from_attributes = True
        populate_by_name = True


class TimestampMixin(BaseModel):
    """Mixin for timestamp fields"""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class TenantMixin(BaseModel):
    """Mixin for tenant isolation"""
    org_id: UUID
