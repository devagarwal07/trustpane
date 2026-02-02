"""
Event Dispatcher - Central hub for event processing

This module provides the infrastructure for event-driven architecture.
When events are appended to the event store, they are dispatched to
all registered handlers.

Architecture:
=============

    Event Store
        │
        ▼
    ┌─────────────────┐
    │ Event Dispatcher │
    └────────┬────────┘
             │
    ┌────────┼────────┬─────────────┐
    ▼        ▼        ▼             ▼
  SLA    Audit    Notification  Projection
Handler  Logger   Service       Builder


Design Choices:
- Async handlers: Non-blocking event processing
- Error isolation: One handler failure doesn't affect others
- Retry support: Transient failures can be retried
- Dead letter: Failed events can be stored for manual review
"""
from typing import Dict, Any, List, Callable, Awaitable, Optional, Set
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass, field
import logging
import asyncio
from collections import defaultdict

from app.models.event import Event, EventType

logger = logging.getLogger(__name__)


# Type alias for event handlers
EventHandler = Callable[[Event], Awaitable[None]]


@dataclass
class HandlerRegistration:
    """Metadata about a registered handler"""
    name: str
    handler: EventHandler
    event_types: Set[EventType]  # Empty set means handle all events
    priority: int = 0  # Higher priority handlers run first
    enabled: bool = True
    
    def should_handle(self, event_type: EventType) -> bool:
        """Check if this handler should process the given event type"""
        if not self.enabled:
            return False
        if not self.event_types:  # Empty set = handle all
            return True
        return event_type in self.event_types


@dataclass
class DispatchResult:
    """Result of dispatching an event"""
    event_id: UUID
    handlers_called: int
    handlers_succeeded: int
    handlers_failed: int
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success(self) -> bool:
        return self.handlers_failed == 0


class EventDispatcher:
    """
    Central event dispatcher.
    
    Receives events from the event store and dispatches them
    to registered handlers.
    
    Usage:
        dispatcher = EventDispatcher()
        
        # Register handlers
        dispatcher.register(
            "sla_coordinator",
            sla_handler.handle_event,
            event_types={EventType.WORKFLOW_CREATED, ...}
        )
        
        # Dispatch an event
        result = await dispatcher.dispatch(event)
    """
    
    def __init__(self):
        self._handlers: List[HandlerRegistration] = []
        self._metrics = {
            "events_dispatched": 0,
            "handlers_invoked": 0,
            "handlers_succeeded": 0,
            "handlers_failed": 0,
        }
    
    # =========================================================
    # HANDLER REGISTRATION
    # =========================================================
    
    def register(
        self,
        name: str,
        handler: EventHandler,
        event_types: Optional[Set[EventType]] = None,
        priority: int = 0
    ) -> None:
        """
        Register an event handler.
        
        Args:
            name: Unique name for this handler (for logging/debugging)
            handler: Async function that takes an Event
            event_types: Set of event types to handle (None = all)
            priority: Higher priority handlers run first
        """
        registration = HandlerRegistration(
            name=name,
            handler=handler,
            event_types=event_types or set(),
            priority=priority
        )
        
        self._handlers.append(registration)
        # Sort by priority (descending)
        self._handlers.sort(key=lambda h: -h.priority)
        
        logger.info(
            f"Registered handler '{name}' for "
            f"{len(event_types or [])} event types"
        )
    
    def unregister(self, name: str) -> bool:
        """Unregister a handler by name"""
        original_len = len(self._handlers)
        self._handlers = [h for h in self._handlers if h.name != name]
        removed = len(self._handlers) < original_len
        
        if removed:
            logger.info(f"Unregistered handler '{name}'")
        
        return removed
    
    def enable_handler(self, name: str) -> bool:
        """Enable a handler"""
        for handler in self._handlers:
            if handler.name == name:
                handler.enabled = True
                return True
        return False
    
    def disable_handler(self, name: str) -> bool:
        """Disable a handler"""
        for handler in self._handlers:
            if handler.name == name:
                handler.enabled = False
                return True
        return False
    
    # =========================================================
    # EVENT DISPATCHING
    # =========================================================
    
    async def dispatch(self, event: Event) -> DispatchResult:
        """
        Dispatch an event to all registered handlers.
        
        Handlers are called sequentially (by priority).
        Errors are logged but don't stop other handlers.
        """
        self._metrics["events_dispatched"] += 1
        
        result = DispatchResult(
            event_id=event.id,
            handlers_called=0,
            handlers_succeeded=0,
            handlers_failed=0
        )
        
        for registration in self._handlers:
            if not registration.should_handle(event.event_type):
                continue
            
            result.handlers_called += 1
            self._metrics["handlers_invoked"] += 1
            
            try:
                await registration.handler(event)
                result.handlers_succeeded += 1
                self._metrics["handlers_succeeded"] += 1
            
            except Exception as e:
                result.handlers_failed += 1
                self._metrics["handlers_failed"] += 1
                
                error_info = {
                    "handler": registration.name,
                    "error": str(e),
                    "event_type": event.event_type.value,
                }
                result.errors.append(error_info)
                
                logger.error(
                    f"Handler '{registration.name}' failed for event "
                    f"{event.id}: {e}",
                    extra=error_info
                )
        
        return result
    
    async def dispatch_many(self, events: List[Event]) -> List[DispatchResult]:
        """Dispatch multiple events"""
        return [await self.dispatch(event) for event in events]
    
    # =========================================================
    # METRICS & STATUS
    # =========================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get dispatcher metrics"""
        return {
            **self._metrics,
            "registered_handlers": len(self._handlers),
            "enabled_handlers": sum(1 for h in self._handlers if h.enabled),
        }
    
    def get_handlers(self) -> List[Dict[str, Any]]:
        """Get information about registered handlers"""
        return [
            {
                "name": h.name,
                "priority": h.priority,
                "enabled": h.enabled,
                "event_types": [et.value for et in h.event_types] if h.event_types else ["*"],
            }
            for h in self._handlers
        ]


# =========================================================
# GLOBAL DISPATCHER INSTANCE
# =========================================================

event_dispatcher = EventDispatcher()


def setup_default_handlers() -> None:
    """
    Register default event handlers.
    
    Called during application startup.
    """
    from app.services.sla_workflow_coordinator import sla_workflow_coordinator
    
    # SLA Coordinator - handles workflow events
    event_dispatcher.register(
        name="sla_coordinator",
        handler=sla_workflow_coordinator.handle_event,
        event_types={
            EventType.WORKFLOW_CREATED,
            EventType.WORKFLOW_TRANSITIONED,
            EventType.WORKFLOW_COMPLETED,
            EventType.WORKFLOW_FAILED,
        },
        priority=100  # High priority
    )
    
    # Note: Additional handlers would be registered here:
    # - Audit logger
    # - Notification service
    # - Metrics collector
    # - Search indexer
    # etc.
    
    logger.info("Default event handlers registered")
