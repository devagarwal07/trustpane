"""
Business Logic Services

This package contains the core business logic services:
- EventStore: Append-only, hash-chained event ledger
- Projector: Builds read models from events
- WorkflowService: Workflow state management (event-sourced)
- SLAService: SLA tracking and enforcement
- AuditService: Audit log management
"""
from app.services.event_store import event_store, EventStore, AppendResult
from app.services.event_projector import (
    projector,
    Projector,
    Projection,
    WorkflowProjection,
    SLAInstanceProjection,
)
from app.services.workflow_service import (
    workflow_service,
    WorkflowService,
    WorkflowState,
    WorkflowType,
    WorkflowStateMachine,
    WorkflowSnapshot,
)

__all__ = [
    # Event Store
    "event_store",
    "EventStore",
    "AppendResult",
    # Projector
    "projector",
    "Projector",
    "Projection",
    "WorkflowProjection",
    "SLAInstanceProjection",
    # Workflow
    "workflow_service",
    "WorkflowService",
    "WorkflowState",
    "WorkflowType",
    "WorkflowStateMachine",
    "WorkflowSnapshot",
]
