"""
Notification Event Handler

Listens to domain events and produces notifications.
"""
from typing import Optional
from uuid import UUID
import logging

from app.models.event import Event, EventType
from app.models.notification import (
    NotificationCreate,
    NotificationChannel,
    NotificationType,
    NotificationPriority,
)
from app.services.notification_service import get_notification_service
from app.services.workflow_service import workflow_service

logger = logging.getLogger(__name__)


class NotificationEventHandler:
    """
    Converts domain events into notifications.
    """
    
    def __init__(self):
        self._handlers = {
            EventType.SLA_WARNING: self._on_sla_warning,
            EventType.SLA_SOFT_BREACH: self._on_sla_breach,
            EventType.SLA_HARD_BREACH: self._on_sla_breach,
            EventType.AGENT_DECISION: self._on_agent_decision,
            EventType.WORKFLOW_ESCALATED: self._on_workflow_escalated,
            EventType.WORKFLOW_ASSIGNED: self._on_workflow_assigned,
            EventType.WORKFLOW_COMPLETED: self._on_workflow_completed,
        }
    
    async def handle_event(self, event: Event) -> None:
        handler = self._handlers.get(event.event_type)
        if handler:
            await handler(event)
    
    async def _on_sla_warning(self, event: Event) -> None:
        workflow_id = event.data.get("workflow_id")
        if not workflow_id:
            return
        
        await self._notify_assignee(
            org_id=event.org_id,
            workflow_id=UUID(workflow_id),
            notification_type=NotificationType.SLA_WARNING,
            title="SLA warning threshold reached",
            message=f"Workflow {workflow_id} is approaching SLA breach.",
            priority=NotificationPriority.HIGH,
            payload={"event_id": str(event.id), "breach_level": event.data.get("breach_level")},
        )
    
    async def _on_sla_breach(self, event: Event) -> None:
        workflow_id = event.data.get("workflow_id")
        if not workflow_id:
            return
        
        breach_type = "hard" if event.event_type == EventType.SLA_HARD_BREACH else "soft"
        await self._notify_assignee(
            org_id=event.org_id,
            workflow_id=UUID(workflow_id),
            notification_type=NotificationType.SLA_BREACH,
            title="SLA breached",
            message=f"Workflow {workflow_id} has a {breach_type} SLA breach.",
            priority=NotificationPriority.CRITICAL,
            payload={"event_id": str(event.id), "breach_type": breach_type},
        )
    
    async def _on_agent_decision(self, event: Event) -> None:
        workflow_id = event.stream_id
        decision_type = event.data.get("decision_type")
        confidence = event.data.get("confidence")
        
        await self._notify_assignee(
            org_id=event.org_id,
            workflow_id=workflow_id,
            notification_type=NotificationType.AGENT_DECISION,
            title="Agent recommendation available",
            message=f"Agent decision: {decision_type} (confidence: {confidence}).",
            priority=NotificationPriority.NORMAL,
            payload={"event_id": str(event.id), "decision": event.data},
        )
    
    async def _on_workflow_escalated(self, event: Event) -> None:
        workflow_id = event.stream_id
        reason = event.data.get("reason")
        
        await self._notify_assignee(
            org_id=event.org_id,
            workflow_id=workflow_id,
            notification_type=NotificationType.WORKFLOW_ESCALATED,
            title="Workflow escalated",
            message=f"Workflow escalated: {reason or 'No reason provided'}.",
            priority=NotificationPriority.HIGH,
            payload={"event_id": str(event.id), "reason": reason},
        )
    
    async def _on_workflow_assigned(self, event: Event) -> None:
        assignee_id = event.data.get("assignee_id")
        if not assignee_id:
            return
        
        service = get_notification_service(event.org_id)
        payload = NotificationCreate(
            recipient_id=str(assignee_id),
            channel=NotificationChannel.IN_APP,
            notification_type=NotificationType.WORKFLOW_ASSIGNED,
            title="Workflow assigned to you",
            message=f"You have been assigned workflow {event.stream_id}.",
            priority=NotificationPriority.NORMAL,
            payload={"event_id": str(event.id), "workflow_id": str(event.stream_id)},
        )
        
        await service.create_notification(payload, auto_send=True)
    
    async def _on_workflow_completed(self, event: Event) -> None:
        workflow_id = event.stream_id
        
        await self._notify_assignee(
            org_id=event.org_id,
            workflow_id=workflow_id,
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            title="Workflow completed",
            message=f"Workflow {workflow_id} has been completed.",
            priority=NotificationPriority.LOW,
            payload={"event_id": str(event.id)},
        )
    
    async def _notify_assignee(
        self,
        org_id: UUID,
        workflow_id: UUID,
        notification_type: NotificationType,
        title: str,
        message: str,
        priority: NotificationPriority,
        payload: dict,
    ) -> None:
        workflow = await workflow_service.get_workflow(org_id, workflow_id)
        if not workflow or not workflow.assignee_id:
            return
        
        service = get_notification_service(org_id)
        notification = NotificationCreate(
            recipient_id=str(workflow.assignee_id),
            channel=NotificationChannel.IN_APP,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            payload={
                **payload,
                "workflow_id": str(workflow_id),
            },
        )
        
        await service.create_notification(notification, auto_send=True)


_notification_handler: Optional[NotificationEventHandler] = None


def get_notification_event_handler() -> NotificationEventHandler:
    """Get or create the notification event handler singleton."""
    global _notification_handler
    if _notification_handler is None:
        _notification_handler = NotificationEventHandler()
    return _notification_handler


def register_notification_handlers(dispatcher) -> None:
    """Register notification handlers with the event dispatcher."""
    handler = get_notification_event_handler()
    
    dispatcher.register(
        name="notification_handler",
        handler=handler.handle_event,
        event_types={
            EventType.SLA_WARNING,
            EventType.SLA_SOFT_BREACH,
            EventType.SLA_HARD_BREACH,
            EventType.AGENT_DECISION,
            EventType.WORKFLOW_ESCALATED,
            EventType.WORKFLOW_ASSIGNED,
            EventType.WORKFLOW_COMPLETED,
        },
        priority=50,
    )

    logger.info("Notification handlers registered")
