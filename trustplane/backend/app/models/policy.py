"""
Policy models for RBAC + ABAC
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class PolicyEffect(str, Enum):
    """Policy effect"""
    ALLOW = "allow"
    DENY = "deny"


class PolicyBase(BaseModel):
    """Policy base fields"""
    name: str
    description: Optional[str] = None
    
    # Policy definition
    effect: PolicyEffect
    actions: List[str]  # e.g., ["workflow:create", "workflow:approve"]
    resources: List[str]  # e.g., ["workflow:*", "sla:definition:*"]
    conditions: Dict[str, Any] = Field(default_factory=dict)
    
    # Priority (lower = higher priority)
    priority: int = 100


class PolicyCreate(PolicyBase):
    """Policy creation payload"""
    pass


class Policy(PolicyBase, TimestampMixin, TenantMixin):
    """Policy model"""
    id: UUID = Field(default_factory=uuid4)
    is_active: bool = True
    version: int = 1
    
    class Config:
        from_attributes = True


class Role(BaseModel, TimestampMixin, TenantMixin):
    """Role model"""
    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None
    policies: List[UUID] = Field(default_factory=list)
    is_system: bool = False  # System roles can't be deleted
    
    class Config:
        from_attributes = True


class Permission(BaseModel):
    """Permission definition"""
    id: str  # e.g., "workflow:create"
    name: str
    description: Optional[str] = None
    resource_type: str
    action: str
