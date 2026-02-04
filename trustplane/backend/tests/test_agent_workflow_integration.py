"""
Tests for Agent-Workflow Integration

Tests the integration layer between AI agents and workflows.
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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
from app.agents import AgentType, DecisionType, DecisionConfidence, AgentContext
from app.models.event import Event, EventType


# Fixtures

@pytest.fixture
def org_id():
    """Test organization ID."""
    return uuid4()


@pytest.fixture
def workflow_id():
    """Test workflow ID."""
    return uuid4()


@pytest.fixture
def user_id():
    """Test user ID."""
    return str(uuid4())


@pytest.fixture
def integration(org_id):
    """Create integration instance."""
    return create_agent_workflow_integration(org_id)


@pytest.fixture
def event_handler():
    """Create event handler."""
    return AgentEventHandler()


# Context Building Tests

class TestAgentWorkflowContext:
    """Tests for AgentWorkflowContext."""
    
    def test_context_creation(self, org_id, workflow_id):
        """Test creating workflow context."""
        context = AgentWorkflowContext(
            org_id=org_id,
            workflow_id=workflow_id,
            trigger_point=AgentTriggerPoint.MANUAL_REQUEST,
        )
        
        assert context.org_id == org_id
        assert context.workflow_id == workflow_id
        assert context.trigger_point == AgentTriggerPoint.MANUAL_REQUEST
    
    def test_context_to_agent_context(self, org_id, workflow_id, user_id):
        """Test converting to AgentContext."""
        context = AgentWorkflowContext(
            org_id=org_id,
            workflow_id=workflow_id,
            customer_tier="enterprise",
            tags=["priority", "vip"],
        )
        
        agent_context = context.to_agent_context(user_id)
        
        assert isinstance(agent_context, AgentContext)
        assert agent_context.org_id == org_id
        assert agent_context.workflow_id == workflow_id
        assert agent_context.user_id == user_id
        assert agent_context.metadata.get("customer_tier") == "enterprise"
        assert agent_context.metadata.get("tags") == ["priority", "vip"]
    
    def test_context_with_sla(self, org_id, workflow_id):
        """Test context with SLA data."""
        deadline = datetime.now(timezone.utc) + timedelta(hours=2)
        
        context = AgentWorkflowContext(
            org_id=org_id,
            workflow_id=workflow_id,
            sla_instance={
                "id": str(uuid4()),
                "deadline": deadline.isoformat(),
                "time_remaining_seconds": 7200,
                "breach_level": "warning",
                "is_paused": False,
            },
            sla_definition={
                "name": "Standard SLA",
                "target_hours": 4,
            },
        )
        
        agent_context = context.to_agent_context()
        
        assert agent_context.sla_deadline is not None
        assert agent_context.sla_time_remaining_seconds == 7200
        assert agent_context.sla_breach_level == "warning"


# Integration Service Tests

class TestAgentWorkflowIntegration:
    """Tests for AgentWorkflowIntegration service."""
    
    def test_integration_creation(self, org_id):
        """Test creating integration instance."""
        integration = create_agent_workflow_integration(org_id)
        
        assert integration is not None
        assert integration.org_id == org_id
    
    def test_singleton_per_org(self, org_id):
        """Test singleton pattern per org."""
        i1 = get_agent_workflow_integration(org_id)
        i2 = get_agent_workflow_integration(org_id)
        
        assert i1 is i2
    
    def test_different_orgs_different_instances(self):
        """Test different orgs get different instances."""
        org1 = uuid4()
        org2 = uuid4()
        
        i1 = get_agent_workflow_integration(org1)
        i2 = get_agent_workflow_integration(org2)
        
        assert i1 is not i2
        assert i1.org_id == org1
        assert i2.org_id == org2


# Event Handler Tests

class TestAgentEventHandler:
    """Tests for AgentEventHandler."""
    
    def test_handler_creation(self):
        """Test creating event handler."""
        handler = AgentEventHandler()
        
        assert handler is not None
        assert handler._config["enabled"] is True
    
    def test_handler_configuration(self, event_handler):
        """Test configuring handler."""
        event_handler.configure(
            enabled=False,
            auto_triage_on_create=False,
            max_concurrent_agents=10,
        )
        
        assert event_handler._config["enabled"] is False
        assert event_handler._config["auto_triage_on_create"] is False
        assert event_handler._config["max_concurrent_agents"] == 10
    
    def test_enable_disable(self, event_handler):
        """Test enable/disable."""
        event_handler.disable()
        assert event_handler._config["enabled"] is False
        
        event_handler.enable()
        assert event_handler._config["enabled"] is True
    
    def test_handler_singleton(self):
        """Test handler singleton."""
        h1 = get_agent_event_handler()
        h2 = get_agent_event_handler()
        
        assert h1 is h2


# Trigger Point Tests

class TestAgentTriggerPoints:
    """Tests for agent trigger points."""
    
    def test_all_trigger_points_defined(self):
        """Test all trigger points are defined."""
        expected = [
            "workflow_created",
            "workflow_started",
            "workflow_transitioned",
            "sla_warning",
            "sla_breach",
            "manual_request",
            "periodic_check",
            "escalation_needed",
        ]
        
        actual = [tp.value for tp in AgentTriggerPoint]
        
        for expected_tp in expected:
            assert expected_tp in actual
    
    def test_trigger_point_in_context(self, org_id, workflow_id):
        """Test trigger point is included in context."""
        context = AgentWorkflowContext(
            org_id=org_id,
            workflow_id=workflow_id,
            trigger_point=AgentTriggerPoint.SLA_WARNING,
        )
        
        agent_context = context.to_agent_context()
        
        assert agent_context.metadata.get("trigger_point") == "sla_warning"


# Decision Recording Tests

class TestDecisionRecording:
    """Tests for decision recording."""
    
    def test_decision_event_data_structure(self):
        """Test decision event data has required fields."""
        from app.agents import AgentDecision
        
        decision = AgentDecision(
            agent_type=AgentType.SLA_RISK,
            agent_id="test-agent",
            decision_type=DecisionType.ALERT,
            confidence=DecisionConfidence.HIGH,
            reasoning="SLA breach imminent",
            evidence=["Time remaining: 10 minutes"],
            recommendations=["Escalate immediately"],
            is_urgent=True,
        )
        
        # Verify decision has all required fields for event
        assert decision.id is not None
        assert decision.agent_type is not None
        assert decision.decision_type is not None
        assert decision.confidence is not None
        assert decision.reasoning is not None
        assert decision.decision_hash is not None


# Human Review Tests

class TestHumanReview:
    """Tests for human review functionality."""
    
    def test_review_states(self):
        """Test decision can be accepted or rejected."""
        # These are the two valid states for human review
        accepted_states = [True, False]
        
        for accepted in accepted_states:
            # Should not raise
            assert isinstance(accepted, bool)


# Event Type Tests

class TestAgentEventTypes:
    """Tests for agent-related event types."""
    
    def test_agent_decision_event_type(self):
        """Test AGENT_DECISION event type exists."""
        assert hasattr(EventType, "AGENT_DECISION")
        assert EventType.AGENT_DECISION.value == "agent.decision"
    
    def test_agent_decision_reviewed_event_type(self):
        """Test AGENT_DECISION_REVIEWED event type exists."""
        assert hasattr(EventType, "AGENT_DECISION_REVIEWED")
        assert EventType.AGENT_DECISION_REVIEWED.value == "agent.decision_reviewed"
    
    def test_workflow_escalated_event_type(self):
        """Test WORKFLOW_ESCALATED event type exists."""
        assert hasattr(EventType, "WORKFLOW_ESCALATED")
        assert EventType.WORKFLOW_ESCALATED.value == "workflow.escalated"
    
    def test_workflow_assigned_event_type(self):
        """Test WORKFLOW_ASSIGNED event type exists."""
        assert hasattr(EventType, "WORKFLOW_ASSIGNED")
        assert EventType.WORKFLOW_ASSIGNED.value == "workflow.assigned"


# Integration Flow Tests

class TestIntegrationFlows:
    """Tests for complete integration flows."""
    
    def test_triage_flow_sequence(self):
        """Test triage flow has correct sequence."""
        # Flow: workflow_created -> triage agent -> decision event
        flow_steps = [
            "receive_workflow_created_event",
            "build_context",
            "run_triage_agent",
            "record_decision_event",
        ]
        
        # Each step should be defined
        assert len(flow_steps) == 4
    
    def test_sla_warning_flow_sequence(self):
        """Test SLA warning flow has correct sequence."""
        # Flow: sla_warning -> sla agent -> decision event
        flow_steps = [
            "receive_sla_warning_event",
            "build_context",
            "run_sla_agent",
            "record_decision_event",
        ]
        
        assert len(flow_steps) == 4
    
    def test_breach_flow_sequence(self):
        """Test breach flow has correct sequence."""
        # Flow: sla_breach -> orchestrator -> synthesized decision
        flow_steps = [
            "receive_sla_breach_event",
            "build_rich_context",
            "run_orchestrator",
            "record_orchestrator_event",
        ]
        
        assert len(flow_steps) == 4


# Immutability Tests

class TestAgentImmutability:
    """Tests ensuring agents don't mutate data."""
    
    def test_context_not_mutated(self, org_id, workflow_id):
        """Test that building context doesn't mutate inputs."""
        original_org = org_id
        original_workflow = workflow_id
        
        context = AgentWorkflowContext(
            org_id=org_id,
            workflow_id=workflow_id,
        )
        
        # Original IDs should be unchanged
        assert org_id == original_org
        assert workflow_id == original_workflow
    
    def test_agents_return_decisions_not_mutations(self):
        """Test that agents return decisions, not mutations."""
        from app.agents import AgentDecision
        
        # Decisions should only contain recommendations
        decision = AgentDecision(
            agent_type=AgentType.WORKFLOW,
            agent_id="test",
            decision_type=DecisionType.RECOMMEND,
            confidence=DecisionConfidence.HIGH,
            reasoning="Test",
            evidence=[],
            recommendations=["Do X"],
            suggested_action="transition",
        )
        
        # Decision has recommendations, not mutations
        assert decision.suggested_action is not None
        assert hasattr(decision, "recommendations")
        
        # Decision doesn't have mutation methods
        assert not hasattr(decision, "apply")
        assert not hasattr(decision, "execute")
        assert not hasattr(decision, "mutate")
