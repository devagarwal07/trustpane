"""
SLA models
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class SLAStatus(str, Enum):
    """SLA instance status"""
    ACTIVE = "active"
    PAUSED = "paused"
    MET = "met"
    SOFT_BREACH = "soft_breach"
    HARD_BREACH = "hard_breach"


class BreachSeverity(str, Enum):
    """Breach severity levels"""
    WARNING = "warning"
    SOFT = "soft"
    HARD = "hard"
    CRITICAL = "critical"


class SLADefinitionBase(BaseModel):
    """SLA definition base fields"""
    name: str
    description: Optional[str] = None
    
    # Time limits
    soft_limit_minutes: int
    hard_limit_minutes: int
    
    # Conditions
    conditions: Dict[str, Any] = Field(default_factory=dict)
    
    # Penalties
    penalty_config: Dict[str, Any] = Field(default_factory=dict)
    
    # Notifications
    notification_config: Dict[str, Any] = Field(default_factory=dict)


class SLADefinitionCreate(SLADefinitionBase):
    """SLA definition creation payload"""
    pass


class SLADefinition(SLADefinitionBase, TimestampMixin, TenantMixin):
    """SLA definition model"""
    id: UUID = Field(default_factory=uuid4)
    is_active: bool = True
    version: int = 1
    
    class Config:
        from_attributes = True


class SLAInstance(BaseModel, TimestampMixin, TenantMixin):
    """
    SLA instance - tracks a specific SLA against a workflow.
    All state changes are recorded as events.
    """
    id: UUID = Field(default_factory=uuid4)
    definition_id: UUID
    workflow_id: UUID
    
    # Status
    status: SLAStatus = SLAStatus.ACTIVE
    
    # Timer tracking
    started_at: datetime = Field(default_factory=datetime.utcnow)
    paused_at: Optional[datetime] = None
    elapsed_minutes: float = 0.0
    
    # Deadlines (computed)
    soft_deadline: datetime
    hard_deadline: datetime
    
    # Breach info
    breached_at: Optional[datetime] = None
    breach_severity: Optional[BreachSeverity] = None
    
    class Config:
        from_attributes = True


class SLABreach(BaseModel, TimestampMixin, TenantMixin):
    """SLA breach record"""
    id: UUID = Field(default_factory=uuid4)
    instance_id: UUID
    workflow_id: UUID
    definition_id: UUID
    
    severity: BreachSeverity
    breach_type: str  # soft, hard
    
    expected_deadline: datetime
    actual_completion: Optional[datetime] = None
    exceeded_by_minutes: float
    
    # Penalty
    penalty_applied: bool = False
    penalty_amount: Optional[float] = None
    penalty_details: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        from_attributes = True
