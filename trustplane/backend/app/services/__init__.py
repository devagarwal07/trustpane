"""
Business Logic Services

This package contains the core business logic services:
- EventStore: Append-only, hash-chained event ledger
- Projector: Builds read models from events
- WorkflowService: Workflow state management (event-sourced)
- SLAService: SLA tracking and enforcement
- AuditService: Audit log management
- AgentWorkflowIntegration: AI agent integration with workflows
- AgentEventHandler: Event-driven agent triggering
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
from app.services.agent_workflow_integration import (
    AgentWorkflowIntegration,
    AgentWorkflowContext,
    AgentTriggerPoint,
    create_agent_workflow_integration,
    get_agent_workflow_integration,
)
from app.services.agent_event_handler import (
    AgentEventHandler,
    get_agent_event_handler,
    register_agent_handlers,
)
from app.services.notification_service import (
    NotificationService,
    create_notification_service,
    get_notification_service,
)
from app.services.notification_event_handler import (
    NotificationEventHandler,
    get_notification_event_handler,
    register_notification_handlers,
)
from app.services.dashboard_service import (
    DashboardService,
    create_dashboard_service,
    get_dashboard_service,
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
    # Agent-Workflow Integration
    "AgentWorkflowIntegration",
    "AgentWorkflowContext",
    "AgentTriggerPoint",
    "create_agent_workflow_integration",
    "get_agent_workflow_integration",
    # Agent Event Handler
    "AgentEventHandler",
    "get_agent_event_handler",
    "register_agent_handlers",
    # Notification Service
    "NotificationService",
    "create_notification_service",
    "get_notification_service",
    # Notification Event Handler
    "NotificationEventHandler",
    "get_notification_event_handler",
    "register_notification_handlers",
    # Dashboard Service
    "DashboardService",
    "create_dashboard_service",
    "get_dashboard_service",
]
