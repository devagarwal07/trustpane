"""
Event Projector - Builds read models from events

Event sourcing separates writes (events) from reads (projections).
This module provides the infrastructure for building read models
by processing events.

Key concepts:
- Projection: A read model built by processing events
- Projector: Code that processes events to update projections
- Snapshot: A cached projection at a specific version
"""
from typing import Dict, Any, List, Optional, Callable, Type
from uuid import UUID
from datetime import datetime
from abc import ABC, abstractmethod
import logging

from app.models.event import Event, EventType
from app.services.event_store import event_store

logger = logging.getLogger(__name__)


class Projection(ABC):
    """
    Base class for projections (read models).
    
    A projection is a view of data optimized for reading,
    built by processing events.
    """
    
    @property
    @abstractmethod
    def projection_name(self) -> str:
        """Unique name for this projection"""
        pass
    
    @abstractmethod
    def apply(self, event: Event) -> None:
        """Apply an event to update the projection"""
        pass
    
    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Get the current state of the projection"""
        pass
    
    def reset(self) -> None:
        """Reset the projection to initial state"""
        pass


class WorkflowProjection(Projection):
    """
    Projection for workflow aggregate.
    
    Builds workflow state by replaying events.
    """
    
    def __init__(self):
        self.reset()
    
    @property
    def projection_name(self) -> str:
        return "workflow"
    
    def reset(self) -> None:
        self._state = {
            "id": None,
            "org_id": None,
            "name": None,
            "description": None,
            "workflow_type": None,
            "current_state": "unknown",
            "config": {},
            "sla_definition_id": None,
            "event_count": 0,
            "created_at": None,
            "updated_at": None,
            "state_history": [],
        }
    
    def apply(self, event: Event) -> None:
        """Apply event to workflow projection"""
        self._state["event_count"] += 1
        self._state["updated_at"] = event.occurred_at
        
        if event.event_type == EventType.WORKFLOW_CREATED:
            self._state.update({
                "id": str(event.stream_id),
                "org_id": str(event.org_id),
                "name": event.data.get("name"),
                "description": event.data.get("description"),
                "workflow_type": event.data.get("workflow_type"),
                "current_state": "pending",
                "config": event.data.get("config", {}),
                "sla_definition_id": event.data.get("sla_definition_id"),
                "created_at": event.occurred_at,
            })
            self._state["state_history"].append({
                "state": "pending",
                "at": event.occurred_at,
                "actor": str(event.actor_id) if event.actor_id else None,
            })
        
        elif event.event_type == EventType.WORKFLOW_TRANSITIONED:
            new_state = event.data.get("to_state")
            self._state["current_state"] = new_state
            self._state["state_history"].append({
                "state": new_state,
                "from_state": event.data.get("from_state"),
                "at": event.occurred_at,
                "actor": str(event.actor_id) if event.actor_id else None,
                "reason": event.data.get("reason"),
            })
        
        elif event.event_type == EventType.WORKFLOW_COMPLETED:
            self._state["current_state"] = "completed"
            self._state["completed_at"] = event.occurred_at
            self._state["state_history"].append({
                "state": "completed",
                "at": event.occurred_at,
            })
        
        elif event.event_type == EventType.WORKFLOW_FAILED:
            self._state["current_state"] = "failed"
            self._state["failed_at"] = event.occurred_at
            self._state["failure_reason"] = event.data.get("reason")
            self._state["state_history"].append({
                "state": "failed",
                "at": event.occurred_at,
                "reason": event.data.get("reason"),
            })
    
    def get_state(self) -> Dict[str, Any]:
        return self._state.copy()


class SLAInstanceProjection(Projection):
    """
    Projection for SLA instance aggregate.
    """
    
    def __init__(self):
        self.reset()
    
    @property
    def projection_name(self) -> str:
        return "sla_instance"
    
    def reset(self) -> None:
        self._state = {
            "id": None,
            "org_id": None,
            "definition_id": None,
            "workflow_id": None,
            "status": "unknown",
            "started_at": None,
            "paused_at": None,
            "total_paused_seconds": 0,
            "soft_deadline": None,
            "hard_deadline": None,
            "breached_at": None,
            "completed_at": None,
            "event_count": 0,
        }
    
    def apply(self, event: Event) -> None:
        """Apply event to SLA instance projection"""
        self._state["event_count"] += 1
        
        if event.event_type == EventType.SLA_STARTED:
            self._state.update({
                "id": str(event.stream_id),
                "org_id": str(event.org_id),
                "definition_id": event.data.get("definition_id"),
                "workflow_id": event.data.get("workflow_id"),
                "status": "active",
                "started_at": event.occurred_at,
                "soft_deadline": event.data.get("soft_deadline"),
                "hard_deadline": event.data.get("hard_deadline"),
            })
        
        elif event.event_type == EventType.SLA_PAUSED:
            self._state["status"] = "paused"
            self._state["paused_at"] = event.occurred_at
        
        elif event.event_type == EventType.SLA_RESUMED:
            if self._state["paused_at"]:
                # Calculate paused duration
                paused_at = datetime.fromisoformat(str(self._state["paused_at"]))
                resumed_at = event.occurred_at if isinstance(event.occurred_at, datetime) else datetime.fromisoformat(str(event.occurred_at))
                paused_seconds = (resumed_at - paused_at).total_seconds()
                self._state["total_paused_seconds"] += paused_seconds
            
            self._state["status"] = "active"
            self._state["paused_at"] = None
        
        elif event.event_type == EventType.SLA_SOFT_BREACH:
            self._state["status"] = "soft_breach"
            self._state["breached_at"] = event.occurred_at
        
        elif event.event_type == EventType.SLA_HARD_BREACH:
            self._state["status"] = "hard_breach"
            self._state["breached_at"] = event.occurred_at
        
        elif event.event_type == EventType.SLA_MET:
            self._state["status"] = "met"
            self._state["completed_at"] = event.occurred_at
    
    def get_state(self) -> Dict[str, Any]:
        return self._state.copy()


class Projector:
    """
    Manages projection building from events.
    
    Usage:
        projector = Projector()
        
        # Rebuild a workflow from events
        workflow_state = await projector.build_projection(
            org_id, workflow_id,
            WorkflowProjection()
        )
    """
    
    def __init__(self):
        self._event_store = event_store
    
    async def build_projection(
        self,
        org_id: UUID,
        stream_id: UUID,
        projection: Projection,
        from_version: int = 0
    ) -> Dict[str, Any]:
        """
        Build a projection by replaying events.
        
        Args:
            org_id: Organization ID
            stream_id: Stream to project
            projection: Projection instance to build
            from_version: Start from this version (for incremental updates)
        
        Returns:
            The projection state after replaying events
        """
        events = await self._event_store.get_stream(org_id, stream_id, from_version)
        
        for event in events:
            projection.apply(event)
        
        return projection.get_state()
    
    async def build_workflow(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> Dict[str, Any]:
        """Convenience method to build workflow projection"""
        return await self.build_projection(
            org_id, workflow_id,
            WorkflowProjection()
        )
    
    async def build_sla_instance(
        self,
        org_id: UUID,
        sla_instance_id: UUID
    ) -> Dict[str, Any]:
        """Convenience method to build SLA instance projection"""
        return await self.build_projection(
            org_id, sla_instance_id,
            SLAInstanceProjection()
        )


# Singleton instance
projector = Projector()
