"""
Workflow State Machine

Implements workflows as event-sourced state machines.
All state changes are events, current state is derived by replay.

Key principles:
1. State transitions are EVENTS (immutable)
2. Current state is DERIVED (not stored directly)
3. Transitions are VALIDATED (against allowed transitions)
4. History is COMPLETE (audit trail via events)

State Machine Design:
=====================

    ┌─────────┐
    │ pending │ (initial state)
    └────┬────┘
         │ start
         ▼
    ┌─────────┐      pause       ┌────────┐
    │ active  │ ───────────────► │ paused │
    └────┬────┘ ◄─────────────── └────────┘
         │         resume
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌─────────┐ ┌────────┐
│completed│ │ failed │
└─────────┘ └────────┘
  (terminal)  (terminal)
"""
from typing import Dict, List, Optional, Set, Any, Tuple
from uuid import UUID, uuid4
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import logging

from app.models.event import Event, EventCreate, EventType
from app.services.event_store import event_store, AppendResult
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


class WorkflowState(str, Enum):
    """All possible workflow states"""
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


@dataclass
class StateTransition:
    """Represents an allowed state transition"""
    from_state: WorkflowState
    to_state: WorkflowState
    requires_reason: bool = False
    allowed_actors: Set[str] = field(default_factory=lambda: {"user", "system", "agent"})


@dataclass
class WorkflowSnapshot:
    """Current state of a workflow (derived from events)"""
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    workflow_type: WorkflowType
    current_state: WorkflowState
    config: Dict[str, Any]
    sla_definition_id: Optional[UUID]
    
    # Derived metadata
    event_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    
    # State history
    state_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Current assignee
    assignee_id: Optional[UUID] = None
    
    def is_terminal(self) -> bool:
        """Check if workflow is in a terminal state"""
        return self.current_state in {
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "name": self.name,
            "description": self.description,
            "workflow_type": self.workflow_type.value,
            "current_state": self.current_state.value,
            "config": self.config,
            "sla_definition_id": str(self.sla_definition_id) if self.sla_definition_id else None,
            "event_count": self.event_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "failure_reason": self.failure_reason,
            "is_terminal": self.is_terminal(),
            "state_history": self.state_history,
            "assignee_id": str(self.assignee_id) if self.assignee_id else None,
        }


class WorkflowStateMachine:
    """
    Defines valid state transitions for workflows.
    
    This is a pure function - no I/O, just transition rules.
    """
    
    # Define all valid transitions
    TRANSITIONS: Dict[WorkflowState, Set[WorkflowState]] = {
        WorkflowState.PENDING: {
            WorkflowState.ACTIVE,     # start
            WorkflowState.CANCELLED,  # cancel before starting
        },
        WorkflowState.ACTIVE: {
            WorkflowState.PAUSED,     # pause
            WorkflowState.COMPLETED,  # complete successfully
            WorkflowState.FAILED,     # fail
            WorkflowState.CANCELLED,  # cancel
        },
        WorkflowState.PAUSED: {
            WorkflowState.ACTIVE,     # resume
            WorkflowState.CANCELLED,  # cancel while paused
            WorkflowState.FAILED,     # fail while paused
        },
        # Terminal states - no transitions out
        WorkflowState.COMPLETED: set(),
        WorkflowState.FAILED: set(),
        WorkflowState.CANCELLED: set(),
    }
    
    # Transitions that require a reason
    REQUIRES_REASON = {
        (WorkflowState.ACTIVE, WorkflowState.FAILED),
        (WorkflowState.PAUSED, WorkflowState.FAILED),
        (WorkflowState.ACTIVE, WorkflowState.CANCELLED),
        (WorkflowState.PAUSED, WorkflowState.CANCELLED),
        (WorkflowState.PENDING, WorkflowState.CANCELLED),
    }
    
    @classmethod
    def can_transition(
        cls,
        from_state: WorkflowState,
        to_state: WorkflowState
    ) -> bool:
        """Check if a transition is valid"""
        allowed = cls.TRANSITIONS.get(from_state, set())
        return to_state in allowed
    
    @classmethod
    def get_allowed_transitions(
        cls,
        from_state: WorkflowState
    ) -> Set[WorkflowState]:
        """Get all allowed transitions from a state"""
        return cls.TRANSITIONS.get(from_state, set())
    
    @classmethod
    def requires_reason(
        cls,
        from_state: WorkflowState,
        to_state: WorkflowState
    ) -> bool:
        """Check if this transition requires a reason"""
        return (from_state, to_state) in cls.REQUIRES_REASON
    
    @classmethod
    def validate_transition(
        cls,
        from_state: WorkflowState,
        to_state: WorkflowState,
        reason: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a state transition.
        
        Returns (is_valid, error_message)
        """
        # Check if transition is allowed
        if not cls.can_transition(from_state, to_state):
            allowed = cls.get_allowed_transitions(from_state)
            allowed_str = ", ".join(s.value for s in allowed) if allowed else "none"
            return False, f"Cannot transition from '{from_state.value}' to '{to_state.value}'. Allowed: {allowed_str}"
        
        # Check if reason is required
        if cls.requires_reason(from_state, to_state) and not reason:
            return False, f"Reason required for transition from '{from_state.value}' to '{to_state.value}'"
        
        return True, None


class WorkflowService:
    """
    Workflow management service.
    
    All operations go through the event store - state is derived from events.
    """
    
    def __init__(self):
        self._event_store = event_store
    
    # =========================================================
    # WORKFLOW CREATION
    # =========================================================
    
    async def create_workflow(
        self,
        org_id: UUID,
        name: str,
        workflow_type: WorkflowType,
        actor_id: UUID,
        description: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        sla_definition_id: Optional[UUID] = None,
        idempotency_key: Optional[str] = None
    ) -> WorkflowSnapshot:
        """
        Create a new workflow by emitting a WORKFLOW_CREATED event.
        
        The workflow starts in PENDING state.
        """
        workflow_id = uuid4()
        
        # Build event data
        event_data = {
            "name": name,
            "description": description,
            "workflow_type": workflow_type.value,
            "config": config or {},
            "sla_definition_id": str(sla_definition_id) if sla_definition_id else None,
        }
        
        # Create the event
        event = EventCreate(
            stream_id=workflow_id,
            event_type=EventType.WORKFLOW_CREATED,
            data=event_data,
            metadata={"initial_state": WorkflowState.PENDING.value},
            actor_id=actor_id,
            actor_type="user",
            idempotency_key=idempotency_key,
        )
        
        # Append to event store
        result = await self._event_store.append(org_id, event, actor_id)
        
        if not result.success:
            raise ValidationError(f"Failed to create workflow: {result.error}")
        
        logger.info(f"Workflow created: {workflow_id} ({name})")
        
        # Return the snapshot
        return await self.get_workflow(org_id, workflow_id)
    
    # =========================================================
    # STATE TRANSITIONS
    # =========================================================
    
    async def transition(
        self,
        org_id: UUID,
        workflow_id: UUID,
        to_state: WorkflowState,
        actor_id: UUID,
        actor_type: str = "user",
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WorkflowSnapshot:
        """
        Transition a workflow to a new state.
        
        1. Get current state by replaying events
        2. Validate the transition
        3. Emit transition event
        4. Return updated snapshot
        """
        # Get current state
        current = await self.get_workflow(org_id, workflow_id)
        
        if not current:
            raise ValidationError(f"Workflow not found: {workflow_id}")
        
        from_state = current.current_state
        
        # Validate transition
        is_valid, error = WorkflowStateMachine.validate_transition(
            from_state, to_state, reason
        )
        
        if not is_valid:
            raise ValidationError(error)
        
        # Determine event type based on target state
        event_type = self._get_transition_event_type(to_state)
        
        # Build event data
        event_data = {
            "from_state": from_state.value,
            "to_state": to_state.value,
            "reason": reason,
        }
        
        # Create transition event
        event = EventCreate(
            stream_id=workflow_id,
            event_type=event_type,
            data=event_data,
            metadata=metadata or {},
            actor_id=actor_id,
            actor_type=actor_type,
        )
        
        # Append to event store
        result = await self._event_store.append(org_id, event, actor_id, actor_type)
        
        if not result.success:
            raise ValidationError(f"Failed to transition workflow: {result.error}")
        
        logger.info(
            f"Workflow {workflow_id} transitioned: "
            f"{from_state.value} → {to_state.value}"
        )
        
        # Return updated snapshot
        return await self.get_workflow(org_id, workflow_id)
    
    async def start(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID
    ) -> WorkflowSnapshot:
        """Start a pending workflow"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.ACTIVE,
            actor_id
        )
    
    async def pause(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID,
        reason: Optional[str] = None
    ) -> WorkflowSnapshot:
        """Pause an active workflow"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.PAUSED,
            actor_id,
            reason=reason
        )
    
    async def resume(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID
    ) -> WorkflowSnapshot:
        """Resume a paused workflow"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.ACTIVE,
            actor_id
        )
    
    async def complete(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WorkflowSnapshot:
        """Complete a workflow successfully"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.COMPLETED,
            actor_id,
            metadata=metadata
        )
    
    async def fail(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID,
        reason: str
    ) -> WorkflowSnapshot:
        """Mark a workflow as failed"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.FAILED,
            actor_id,
            reason=reason
        )
    
    async def cancel(
        self,
        org_id: UUID,
        workflow_id: UUID,
        actor_id: UUID,
        reason: str
    ) -> WorkflowSnapshot:
        """Cancel a workflow"""
        return await self.transition(
            org_id, workflow_id,
            WorkflowState.CANCELLED,
            actor_id,
            reason=reason
        )
    
    # =========================================================
    # STATE RECONSTRUCTION (via Event Replay)
    # =========================================================
    
    async def get_workflow(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> Optional[WorkflowSnapshot]:
        """
        Get current workflow state by replaying all events.
        
        This is the core of event sourcing - state is DERIVED, not stored.
        """
        events = await self._event_store.get_stream(org_id, workflow_id)
        
        if not events:
            return None
        
        # Apply events to build snapshot
        snapshot = self._apply_events(events, org_id, workflow_id)
        
        return snapshot
    
    async def get_workflow_at_version(
        self,
        org_id: UUID,
        workflow_id: UUID,
        version: int
    ) -> Optional[WorkflowSnapshot]:
        """
        Get workflow state at a specific version (time travel).
        
        Useful for:
        - Debugging
        - Audit investigations
        - Understanding how state evolved
        """
        events = await self._event_store.get_stream(
            org_id, workflow_id,
            from_version=0,
            to_version=version
        )
        
        if not events:
            return None
        
        return self._apply_events(events, org_id, workflow_id)
    
    def _apply_events(
        self,
        events: List[Event],
        org_id: UUID,
        workflow_id: UUID
    ) -> WorkflowSnapshot:
        """
        Apply a sequence of events to build workflow snapshot.
        
        This is the REDUCER function - pure, deterministic, side-effect free.
        """
        # Initialize empty snapshot
        snapshot = WorkflowSnapshot(
            id=workflow_id,
            org_id=org_id,
            name="",
            description=None,
            workflow_type=WorkflowType.CUSTOM,
            current_state=WorkflowState.PENDING,
            config={},
            sla_definition_id=None,
        )
        
        for event in events:
            snapshot = self._apply_event(snapshot, event)
        
        return snapshot
    
    def _apply_event(
        self,
        snapshot: WorkflowSnapshot,
        event: Event
    ) -> WorkflowSnapshot:
        """Apply a single event to a snapshot"""
        snapshot.event_count += 1
        snapshot.updated_at = event.occurred_at if isinstance(event.occurred_at, datetime) else datetime.fromisoformat(str(event.occurred_at))
        
        if event.event_type == EventType.WORKFLOW_CREATED:
            snapshot.name = event.data.get("name", "")
            snapshot.description = event.data.get("description")
            snapshot.workflow_type = WorkflowType(event.data.get("workflow_type", "custom"))
            snapshot.config = event.data.get("config", {})
            snapshot.current_state = WorkflowState.PENDING
            snapshot.created_at = snapshot.updated_at
            
            sla_id = event.data.get("sla_definition_id")
            if sla_id:
                snapshot.sla_definition_id = UUID(sla_id)
            
            snapshot.state_history.append({
                "state": WorkflowState.PENDING.value,
                "at": str(snapshot.updated_at),
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "event": "created",
            })
        
        elif event.event_type == EventType.WORKFLOW_TRANSITIONED:
            new_state = WorkflowState(event.data.get("to_state"))
            snapshot.current_state = new_state
            
            snapshot.state_history.append({
                "state": new_state.value,
                "from_state": event.data.get("from_state"),
                "at": str(snapshot.updated_at),
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "actor_type": event.actor_type,
                "reason": event.data.get("reason"),
            })
        
        elif event.event_type == EventType.WORKFLOW_COMPLETED:
            snapshot.current_state = WorkflowState.COMPLETED
            snapshot.completed_at = snapshot.updated_at
            
            snapshot.state_history.append({
                "state": WorkflowState.COMPLETED.value,
                "at": str(snapshot.updated_at),
                "actor_id": str(event.actor_id) if event.actor_id else None,
            })
        
        elif event.event_type == EventType.WORKFLOW_FAILED:
            snapshot.current_state = WorkflowState.FAILED
            snapshot.failed_at = snapshot.updated_at
            snapshot.failure_reason = event.data.get("reason")
            
            snapshot.state_history.append({
                "state": WorkflowState.FAILED.value,
                "at": str(snapshot.updated_at),
                "reason": snapshot.failure_reason,
            })
        
        return snapshot
    
    # =========================================================
    # QUERIES
    # =========================================================
    
    async def list_workflows(
        self,
        org_id: UUID,
        state_filter: Optional[WorkflowState] = None,
        workflow_type: Optional[WorkflowType] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[WorkflowSnapshot]:
        """
        List workflows for an organization.
        
        Note: In production, you'd have a read model (projection table)
        for efficient queries. For now, we query event streams.
        """
        # This is a simplified implementation
        # In production, use a materialized projection table
        from app.db.supabase import get_supabase_client
        
        client = get_supabase_client()
        
        # Get distinct stream IDs from events
        query = (
            client.table("events")
            .select("stream_id")
            .eq("org_id", str(org_id))
            .eq("stream_type", "workflow")
            .order("occurred_at", desc=True)
        )
        
        result = query.execute()
        
        # Deduplicate stream IDs
        seen = set()
        stream_ids = []
        for row in result.data:
            sid = row["stream_id"]
            if sid not in seen:
                seen.add(sid)
                stream_ids.append(UUID(sid))
        
        # Build snapshots
        workflows = []
        for stream_id in stream_ids[offset:offset + limit]:
            snapshot = await self.get_workflow(org_id, stream_id)
            if snapshot:
                # Apply filters
                if state_filter and snapshot.current_state != state_filter:
                    continue
                if workflow_type and snapshot.workflow_type != workflow_type:
                    continue
                workflows.append(snapshot)
        
        return workflows
    
    async def get_allowed_transitions(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> Dict[str, Any]:
        """Get allowed transitions for a workflow's current state"""
        snapshot = await self.get_workflow(org_id, workflow_id)
        
        if not snapshot:
            raise ValidationError(f"Workflow not found: {workflow_id}")
        
        allowed = WorkflowStateMachine.get_allowed_transitions(snapshot.current_state)
        
        return {
            "current_state": snapshot.current_state.value,
            "is_terminal": snapshot.is_terminal(),
            "allowed_transitions": [
                {
                    "to_state": s.value,
                    "requires_reason": WorkflowStateMachine.requires_reason(
                        snapshot.current_state, s
                    ),
                }
                for s in allowed
            ],
        }
    
    # =========================================================
    # HELPERS
    # =========================================================
    
    def _get_transition_event_type(self, to_state: WorkflowState) -> EventType:
        """Map target state to event type"""
        mapping = {
            WorkflowState.COMPLETED: EventType.WORKFLOW_COMPLETED,
            WorkflowState.FAILED: EventType.WORKFLOW_FAILED,
        }
        return mapping.get(to_state, EventType.WORKFLOW_TRANSITIONED)


# Singleton instance
workflow_service = WorkflowService()
