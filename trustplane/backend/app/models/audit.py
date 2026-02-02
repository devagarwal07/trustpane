"""
Audit log models
"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TenantMixin


class AuditAction(str, Enum):
    """Audit action types"""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    LOGIN = "login"
    LOGOUT = "logout"
    EXPORT = "export"


class AuditLog(BaseModel, TenantMixin):
    """
    Immutable audit log entry.
    Provides complete traceability for compliance.
    """
    id: UUID = Field(default_factory=uuid4)
    
    # Actor
    actor_id: UUID
    actor_type: str  # user, system, agent
    actor_email: Optional[str] = None
    
    # Action
    action: AuditAction
    resource_type: str  # workflow, sla, policy, etc.
    resource_id: UUID
    
    # Details
    reason: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Context
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Linked event (if any)
    event_id: Optional[UUID] = None
    
    # Timestamp
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class AuditLogCreate(BaseModel):
    """Audit log creation payload"""
    action: AuditAction
    resource_type: str
    resource_id: UUID
    reason: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
