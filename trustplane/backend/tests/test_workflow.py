"""
Tests for Workflow State Machine
"""
import pytest
from uuid import uuid4

from app.services.workflow_service import (
    WorkflowState,
    WorkflowType,
    WorkflowStateMachine,
    WorkflowSnapshot,
)


class TestWorkflowStateMachine:
    """Tests for state machine transition rules"""
    
    def test_valid_transitions_from_pending(self):
        """Pending can transition to active or cancelled"""
        assert WorkflowStateMachine.can_transition(
            WorkflowState.PENDING, WorkflowState.ACTIVE
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.PENDING, WorkflowState.CANCELLED
        )
        # Cannot skip to completed
        assert not WorkflowStateMachine.can_transition(
            WorkflowState.PENDING, WorkflowState.COMPLETED
        )
    
    def test_valid_transitions_from_active(self):
        """Active can pause, complete, fail, or cancel"""
        assert WorkflowStateMachine.can_transition(
            WorkflowState.ACTIVE, WorkflowState.PAUSED
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.ACTIVE, WorkflowState.COMPLETED
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.ACTIVE, WorkflowState.FAILED
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.ACTIVE, WorkflowState.CANCELLED
        )
    
    def test_valid_transitions_from_paused(self):
        """Paused can resume, cancel, or fail"""
        assert WorkflowStateMachine.can_transition(
            WorkflowState.PAUSED, WorkflowState.ACTIVE
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.PAUSED, WorkflowState.CANCELLED
        )
        assert WorkflowStateMachine.can_transition(
            WorkflowState.PAUSED, WorkflowState.FAILED
        )
        # Cannot complete directly from paused
        assert not WorkflowStateMachine.can_transition(
            WorkflowState.PAUSED, WorkflowState.COMPLETED
        )
    
    def test_terminal_states_have_no_transitions(self):
        """Completed, failed, and cancelled are terminal"""
        for terminal in [WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED]:
            allowed = WorkflowStateMachine.get_allowed_transitions(terminal)
            assert len(allowed) == 0, f"{terminal.value} should have no transitions"
    
    def test_requires_reason_for_failure(self):
        """Failing requires a reason"""
        assert WorkflowStateMachine.requires_reason(
            WorkflowState.ACTIVE, WorkflowState.FAILED
        )
        assert WorkflowStateMachine.requires_reason(
            WorkflowState.PAUSED, WorkflowState.FAILED
        )
    
    def test_requires_reason_for_cancellation(self):
        """Cancellation requires a reason"""
        assert WorkflowStateMachine.requires_reason(
            WorkflowState.ACTIVE, WorkflowState.CANCELLED
        )
        assert WorkflowStateMachine.requires_reason(
            WorkflowState.PENDING, WorkflowState.CANCELLED
        )
    
    def test_validate_transition_success(self):
        """Valid transition passes validation"""
        is_valid, error = WorkflowStateMachine.validate_transition(
            WorkflowState.PENDING,
            WorkflowState.ACTIVE
        )
        assert is_valid
        assert error is None
    
    def test_validate_transition_invalid(self):
        """Invalid transition fails validation"""
        is_valid, error = WorkflowStateMachine.validate_transition(
            WorkflowState.PENDING,
            WorkflowState.COMPLETED  # Cannot skip to completed
        )
        assert not is_valid
        assert "Cannot transition" in error
    
    def test_validate_transition_missing_reason(self):
        """Transition requiring reason fails without it"""
        is_valid, error = WorkflowStateMachine.validate_transition(
            WorkflowState.ACTIVE,
            WorkflowState.FAILED,
            reason=None  # Missing required reason
        )
        assert not is_valid
        assert "Reason required" in error
    
    def test_validate_transition_with_reason(self):
        """Transition passes with required reason"""
        is_valid, error = WorkflowStateMachine.validate_transition(
            WorkflowState.ACTIVE,
            WorkflowState.FAILED,
            reason="System error occurred"
        )
        assert is_valid
        assert error is None


class TestWorkflowSnapshot:
    """Tests for WorkflowSnapshot"""
    
    def test_is_terminal_completed(self):
        """Completed workflows are terminal"""
        snapshot = WorkflowSnapshot(
            id=uuid4(),
            org_id=uuid4(),
            name="Test",
            description=None,
            workflow_type=WorkflowType.CUSTOM,
            current_state=WorkflowState.COMPLETED,
            config={},
            sla_definition_id=None,
        )
        assert snapshot.is_terminal()
    
    def test_is_terminal_failed(self):
        """Failed workflows are terminal"""
        snapshot = WorkflowSnapshot(
            id=uuid4(),
            org_id=uuid4(),
            name="Test",
            description=None,
            workflow_type=WorkflowType.CUSTOM,
            current_state=WorkflowState.FAILED,
            config={},
            sla_definition_id=None,
        )
        assert snapshot.is_terminal()
    
    def test_is_not_terminal_active(self):
        """Active workflows are not terminal"""
        snapshot = WorkflowSnapshot(
            id=uuid4(),
            org_id=uuid4(),
            name="Test",
            description=None,
            workflow_type=WorkflowType.CUSTOM,
            current_state=WorkflowState.ACTIVE,
            config={},
            sla_definition_id=None,
        )
        assert not snapshot.is_terminal()
    
    def test_to_dict_has_required_fields(self):
        """to_dict includes all required fields"""
        snapshot = WorkflowSnapshot(
            id=uuid4(),
            org_id=uuid4(),
            name="Test Workflow",
            description="A test",
            workflow_type=WorkflowType.SUPPORT_TICKET,
            current_state=WorkflowState.ACTIVE,
            config={"priority": "high"},
            sla_definition_id=uuid4(),
        )
        
        data = snapshot.to_dict()
        
        assert "id" in data
        assert "name" in data
        assert data["name"] == "Test Workflow"
        assert data["workflow_type"] == "support_ticket"
        assert data["current_state"] == "active"
        assert data["is_terminal"] is False


class TestWorkflowTypes:
    """Tests for workflow type enum"""
    
    def test_all_workflow_types_exist(self):
        """All expected workflow types exist"""
        types = [t.value for t in WorkflowType]
        
        assert "support_ticket" in types
        assert "incident" in types
        assert "change_request" in types
        assert "approval" in types
        assert "custom" in types
    
    def test_workflow_type_from_string(self):
        """Can create WorkflowType from string"""
        wt = WorkflowType("support_ticket")
        assert wt == WorkflowType.SUPPORT_TICKET
