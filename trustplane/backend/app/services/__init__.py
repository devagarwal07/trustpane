"""
Business Logic Services

This package contains the core business logic services:
- EventStore: Append-only, hash-chained event ledger
- Projector: Builds read models from events
- WorkflowService: Workflow state management
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
]
