"""
Workflow models

Note: The authoritative WorkflowState and WorkflowType enums 
are in app.services.workflow_service to keep the state machine 
logic together. These models are for API/persistence compatibility.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class WorkflowState(str, Enum):
    """
    Workflow states (mirror of service enum for model compatibility).
    
    State Machine:
    ┌─────────┐
    │ pending │ ──► active ──► completed
    └─────────┘      │  ▲         
                     │  │       
                     ▼  │       
                   paused       
                     │          
                     ▼          
                   failed/cancelled
    """
    PENDING = "pending"       # Created but not started
    ACTIVE = "active"         # In progress
    PAUSED = "paused"         # Temporarily halted
    COMPLETED = "completed"   # Successfully finished
    FAILED = "failed"         # Terminated with error
    CANCELLED = "cancelled"   # Manually cancelled


class WorkflowType(str, Enum):
    """Types of workflows"""
    SUPPORT_TICKET = "support_ticket"
    INCIDENT = "incident"
    CHANGE_REQUEST = "change_request"
    APPROVAL = "approval"
    ONBOARDING = "onboarding"
    CUSTOM = "custom"


class WorkflowBase(BaseModel):
    """Workflow base fields"""
    name: str
    description: Optional[str] = None
    workflow_type: str = "custom"
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(WorkflowBase):
    """Workflow creation payload"""
    sla_definition_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None


class Workflow(WorkflowBase, TimestampMixin, TenantMixin):
    """
    Workflow model - state is computed from events, not stored directly.
    This ensures consistency with event-sourced architecture.
    """
    id: UUID = Field(default_factory=uuid4)
    current_state: WorkflowState = WorkflowState.PENDING
    sla_definition_id: Optional[UUID] = None
    
    # Computed from events
    event_count: int = 0
    last_event_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class WorkflowTransition(BaseModel):
    """Workflow state transition request"""
    to_state: WorkflowState
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
