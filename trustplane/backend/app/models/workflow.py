"""
Workflow models
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class WorkflowState(str, Enum):
    """Workflow states"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowBase(BaseModel):
    """Workflow base fields"""
    name: str
    description: Optional[str] = None
    workflow_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(WorkflowBase):
    """Workflow creation payload"""
    sla_definition_id: Optional[UUID] = None


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
