"""
Organization (tenant) models
"""
from datetime import datetime
from typing import Optional, List
from pydantic import Field
from uuid import UUID, uuid4

from app.models.base import BaseModel, TimestampMixin


class OrganizationBase(BaseModel):
    """Organization base fields"""
    name: str
    slug: str
    settings: dict = Field(default_factory=dict)


class OrganizationCreate(OrganizationBase):
    """Organization creation payload"""
    pass


class OrganizationUpdate(BaseModel):
    """Organization update payload"""
    name: Optional[str] = None
    settings: Optional[dict] = None


class Organization(OrganizationBase, TimestampMixin):
    """Organization model"""
    id: UUID = Field(default_factory=uuid4)
    is_active: bool = True
    subscription_tier: str = "free"
    
    class Config:
        from_attributes = True
