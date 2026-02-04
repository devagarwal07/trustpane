"""
Event models for event sourcing
"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import Field
from uuid import UUID, uuid4
from enum import Enum

from app.models.base import BaseModel, TenantMixin


class EventType(str, Enum):
    """Event types in the system"""
    # Workflow events
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_TRANSITIONED = "workflow.transitioned"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_ASSIGNED = "workflow.assigned"
    WORKFLOW_ESCALATED = "workflow.escalated"
    
    # SLA events
    SLA_STARTED = "sla.started"
    SLA_PAUSED = "sla.paused"
    SLA_RESUMED = "sla.resumed"
    SLA_SOFT_BREACH = "sla.soft_breach"
    SLA_HARD_BREACH = "sla.hard_breach"
    SLA_MET = "sla.met"
    SLA_WARNING = "sla.warning"
    
    # Agent events
    AGENT_DECISION = "agent.decision"
    AGENT_ESCALATION = "agent.escalation"
    AGENT_DECISION_REVIEWED = "agent.decision_reviewed"
    AGENT_RECOMMENDATION_APPLIED = "agent.recommendation_applied"
    
    # Policy events
    POLICY_EVALUATED = "policy.evaluated"
    POLICY_VIOLATION = "policy.violation"
    
    # Audit events
    USER_ACTION = "user.action"
    SYSTEM_ACTION = "system.action"


class Event(BaseModel, TenantMixin):
    """
    Immutable event record.
    Forms the foundation of the event-sourced architecture.
    """
    id: UUID = Field(default_factory=uuid4)
    stream_id: UUID  # Aggregate ID (e.g., workflow_id)
    event_type: EventType
    version: int  # Event version within stream
    data: Dict[str, Any]  # Event payload
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Integrity fields
    hash: str  # SHA-256 hash of event
    previous_hash: str  # Hash of previous event in stream
    
    # Timestamps
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Actor
    actor_id: Optional[UUID] = None
    actor_type: str = "user"  # user, system, agent
    
    class Config:
        from_attributes = True


class EventCreate(BaseModel):
    """Event creation payload"""
    stream_id: UUID
    event_type: EventType
    data: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    actor_id: Optional[UUID] = None
    actor_type: str = "user"
    idempotency_key: Optional[str] = None
