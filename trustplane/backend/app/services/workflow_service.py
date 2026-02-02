"""
Workflow Service - State machine on event sourcing
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime

from app.models.workflow import Workflow, WorkflowCreate, WorkflowState, WorkflowTransition
from app.models.event import EventCreate, EventType
from app.services.event_store import event_store


class WorkflowService:
    """
    Workflow management with event-sourced state.
    State is computed by replaying events, never stored directly.
    """
    
    # Valid state transitions
    TRANSITIONS = {
        WorkflowState.PENDING: [WorkflowState.IN_PROGRESS, WorkflowState.CANCELLED],
        WorkflowState.IN_PROGRESS: [WorkflowState.AWAITING_APPROVAL, WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED],
        WorkflowState.AWAITING_APPROVAL: [WorkflowState.APPROVED, WorkflowState.REJECTED],
        WorkflowState.APPROVED: [WorkflowState.COMPLETED, WorkflowState.FAILED],
        WorkflowState.REJECTED: [WorkflowState.PENDING],  # Can retry
        WorkflowState.COMPLETED: [],  # Terminal state
        WorkflowState.FAILED: [WorkflowState.PENDING],  # Can retry
        WorkflowState.CANCELLED: [],  # Terminal state
    }
    
    async def create(
        self,
        org_id: UUID,
        workflow: WorkflowCreate,
        actor_id: UUID
    ) -> Workflow:
        """Create a new workflow"""
        raise NotImplementedError("Will be implemented in Step 6")
    
    async def transition(
        self,
        org_id: UUID,
        workflow_id: UUID,
        transition: WorkflowTransition,
        actor_id: UUID
    ) -> Workflow:
        """Transition workflow to new state"""
        raise NotImplementedError("Will be implemented in Step 6")
    
    async def get(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> Optional[Workflow]:
        """Get workflow by ID (state computed from events)"""
        raise NotImplementedError("Will be implemented in Step 6")
    
    async def rebuild_state(
        self,
        org_id: UUID,
        workflow_id: UUID
    ) -> WorkflowState:
        """Rebuild workflow state by replaying events"""
        raise NotImplementedError("Will be implemented in Step 6")
    
    def validate_transition(
        self,
        from_state: WorkflowState,
        to_state: WorkflowState
    ) -> bool:
        """Check if state transition is valid"""
        allowed = self.TRANSITIONS.get(from_state, [])
        return to_state in allowed


# Singleton instance
workflow_service = WorkflowService()
