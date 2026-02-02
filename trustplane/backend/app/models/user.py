"""
User models
"""
from datetime import datetime
from typing import Optional, List
from pydantic import Field, EmailStr
from uuid import UUID, uuid4

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class UserBase(BaseModel):
    """User base fields"""
    email: EmailStr
    full_name: str


class UserCreate(UserBase):
    """User creation payload"""
    org_id: UUID
    role: str = "member"


class UserUpdate(BaseModel):
    """User update payload"""
    full_name: Optional[str] = None
    role: Optional[str] = None


class User(UserBase, TimestampMixin, TenantMixin):
    """User model"""
    id: UUID = Field(default_factory=uuid4)
    role: str = "member"
    is_active: bool = True
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True
