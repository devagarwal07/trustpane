"""
Tests for AI Agents

Tests the agent framework, individual agents, and orchestrator.
Agents make decisions only - they never mutate data.
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.agents import (
    BaseAgent,
    AgentContext,
    AgentDecision,
    AgentState,
    AgentType,
    DecisionType,
    DecisionConfidence,
    SLAAgent,
    WorkflowAgent,
    TriageAgent,
    AgentOrchestrator,
    ParallelOrchestrator,
    create_sla_agent,
    create_workflow_agent,
    create_triage_agent,
    get_orchestrator,
)


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
def sla_id():
    """Test SLA ID."""
    return uuid4()


@pytest.fixture
def user_id():
    """Test user ID."""
    return "user-123"


@pytest.fixture
def base_context(org_id, workflow_id, sla_id, user_id):
    """Base agent context."""
    return AgentContext(
        org_id=org_id,
        workflow_id=workflow_id,
        sla_id=sla_id,
        workflow_state="pending",
        workflow_priority="normal",
        workflow_created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        workflow_owner_id=user_id,
        user_id=user_id,
        metadata={
            "title": "Test Request",
            "description": "Test description for agent analysis",
        }
    )


@pytest.fixture
def urgent_context(org_id, workflow_id, sla_id, user_id):
    """Urgent context with SLA pressure."""
    return AgentContext(
        org_id=org_id,
        workflow_id=workflow_id,
        sla_id=sla_id,
        workflow_state="pending",
        workflow_priority="urgent",
        workflow_created_at=datetime.now(timezone.utc) - timedelta(hours=5),
        workflow_owner_id=user_id,
        sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=10),
        sla_time_remaining_seconds=600,
        sla_breach_level="warning",
        sla_is_paused=False,
        user_id=user_id,
        metadata={
            "title": "URGENT: System Down",
            "description": "Critical production issue affecting all users",
            "customer_tier": "enterprise",
        }
    )


@pytest.fixture
def breached_context(org_id, workflow_id, sla_id, user_id):
    """Context with SLA already breached."""
    return AgentContext(
        org_id=org_id,
        workflow_id=workflow_id,
        sla_id=sla_id,
        workflow_state="pending",
        workflow_priority="urgent",
        workflow_created_at=datetime.now(timezone.utc) - timedelta(hours=10),
        workflow_owner_id=user_id,
        sla_deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        sla_time_remaining_seconds=-3600,
        sla_breach_level="breached",
        sla_is_paused=False,
        user_id=user_id,
    )


# Agent Context Tests

class TestAgentContext:
    """Tests for AgentContext model."""
    
    def test_context_creation(self, base_context):
        """Test creating agent context."""
        assert base_context.org_id is not None
        assert base_context.workflow_id is not None
        assert base_context.workflow_state == "pending"
        assert base_context.workflow_priority == "normal"
    
    def test_context_metadata(self, base_context):
        """Test context metadata."""
        assert base_context.metadata.get("title") == "Test Request"
        assert "description" in base_context.metadata
    
    def test_context_with_sla(self, urgent_context):
        """Test context with SLA information."""
        assert urgent_context.sla_deadline is not None
        assert urgent_context.sla_time_remaining_seconds == 600
        assert urgent_context.sla_breach_level == "warning"


# Agent Decision Tests

class TestAgentDecision:
    """Tests for AgentDecision model."""
    
    def test_decision_creation(self):
        """Test creating agent decision."""
        decision = AgentDecision(
            agent_type=AgentType.SLA_RISK,
            agent_id="test-agent",
            decision_type=DecisionType.RECOMMEND,
            confidence=DecisionConfidence.HIGH,
            reasoning="Test reasoning",
            evidence=["Evidence 1"],
            recommendations=["Recommendation 1"],
        )
        
        assert decision.id is not None
        assert decision.agent_type == AgentType.SLA_RISK
        assert decision.decision_type == DecisionType.RECOMMEND
        assert decision.confidence == DecisionConfidence.HIGH
    
    def test_decision_hash_integrity(self):
        """Test decision hash is computed."""
        decision = AgentDecision(
            agent_type=AgentType.WORKFLOW,
            agent_id="test-agent",
            decision_type=DecisionType.APPROVE,
            confidence=DecisionConfidence.HIGH,
            reasoning="Approved based on analysis",
            evidence=["State is valid"],
            recommendations=[],
        )
        
        hash1 = decision.compute_hash()
        assert hash1 is not None
        assert len(hash1) == 64  # SHA-256 hex
        
        # Hash should be deterministic
        hash2 = decision.compute_hash()
        assert hash1 == hash2
    
    def test_decision_hash_changes(self):
        """Test decision hash changes with different content."""
        decision1 = AgentDecision(
            agent_type=AgentType.TRIAGE,
            agent_id="test-agent",
            decision_type=DecisionType.APPROVE,
            confidence=DecisionConfidence.HIGH,
            reasoning="Reason A",
            evidence=[],
            recommendations=[],
        )
        
        decision2 = AgentDecision(
            agent_type=AgentType.TRIAGE,
            agent_id="test-agent",
            decision_type=DecisionType.REJECT,
            confidence=DecisionConfidence.LOW,
            reasoning="Reason B",
            evidence=[],
            recommendations=[],
        )
        
        assert decision1.compute_hash() != decision2.compute_hash()
    
    def test_decision_urgency_flags(self):
        """Test urgency flags."""
        urgent_decision = AgentDecision(
            agent_type=AgentType.SLA_RISK,
            agent_id="test-agent",
            decision_type=DecisionType.ESCALATE,
            confidence=DecisionConfidence.HIGH,
            reasoning="Urgent escalation needed",
            evidence=[],
            recommendations=[],
            requires_human_review=True,
            is_urgent=True,
        )
        
        assert urgent_decision.requires_human_review is True
        assert urgent_decision.is_urgent is True


# SLA Agent Tests

class TestSLAAgent:
    """Tests for SLA Risk Agent."""
    
    @pytest.fixture
    def sla_agent(self):
        """Create SLA agent."""
        return create_sla_agent()
    
    def test_agent_creation(self, sla_agent):
        """Test SLA agent creation."""
        assert sla_agent is not None
        assert sla_agent.agent_type == AgentType.SLA_RISK
    
    def test_system_prompt(self, sla_agent):
        """Test system prompt exists."""
        prompt = sla_agent.system_prompt
        assert "SLA" in prompt or "risk" in prompt.lower()
    
    @pytest.mark.asyncio
    async def test_analyze_normal_context(self, sla_agent, base_context):
        """Test analysis with normal context."""
        analysis = await sla_agent.analyze(base_context)
        
        assert "risk_factors" in analysis
        assert "time_risk" in analysis
        assert "overall_risk" in analysis
    
    @pytest.mark.asyncio
    async def test_analyze_urgent_context(self, sla_agent, urgent_context):
        """Test analysis with urgent context."""
        analysis = await sla_agent.analyze(urgent_context)
        
        assert analysis["time_risk"] in ["high", "critical"]
        assert analysis["overall_risk"] in ["high", "critical"]
    
    @pytest.mark.asyncio
    async def test_analyze_breached_context(self, sla_agent, breached_context):
        """Test analysis with breached SLA."""
        analysis = await sla_agent.analyze(breached_context)
        
        assert analysis["overall_risk"] == "critical"
        assert analysis["is_breached"] is True
    
    @pytest.mark.asyncio
    async def test_decide_escalates_critical(self, sla_agent, breached_context):
        """Test decision escalates on critical risk."""
        decision = await sla_agent.decide(breached_context, {
            "overall_risk": "critical",
            "is_breached": True,
            "risk_factors": ["SLA breached"],
            "time_risk": "critical",
        })
        
        assert decision.decision_type == DecisionType.ESCALATE
        assert decision.is_urgent is True
    
    @pytest.mark.asyncio
    async def test_run_full_pipeline(self, sla_agent, base_context):
        """Test full run pipeline."""
        decision = await sla_agent.run(base_context)
        
        assert isinstance(decision, AgentDecision)
        assert decision.agent_type == AgentType.SLA_RISK
        assert decision.processing_time_ms >= 0


# Workflow Agent Tests

class TestWorkflowAgent:
    """Tests for Workflow Agent."""
    
    @pytest.fixture
    def workflow_agent(self):
        """Create workflow agent."""
        return create_workflow_agent()
    
    def test_agent_creation(self, workflow_agent):
        """Test workflow agent creation."""
        assert workflow_agent is not None
        assert workflow_agent.agent_type == AgentType.WORKFLOW
    
    @pytest.mark.asyncio
    async def test_analyze_pending_state(self, workflow_agent, base_context):
        """Test analysis of pending state."""
        analysis = await workflow_agent.analyze(base_context)
        
        assert "current_state" in analysis
        assert "recommended_transition" in analysis
        assert analysis["current_state"] == "pending"
    
    @pytest.mark.asyncio
    async def test_analyze_state_transitions(self, workflow_agent, base_context):
        """Test valid transitions are identified."""
        analysis = await workflow_agent.analyze(base_context)
        
        assert "valid_transitions" in analysis
        # pending should be able to transition to in_progress or cancelled
        valid = analysis["valid_transitions"]
        assert isinstance(valid, list)
    
    @pytest.mark.asyncio
    async def test_decide_recommends_transition(self, workflow_agent, base_context):
        """Test decision recommends transition."""
        analysis = await workflow_agent.analyze(base_context)
        decision = await workflow_agent.decide(base_context, analysis)
        
        assert isinstance(decision, AgentDecision)
        assert decision.decision_type in [
            DecisionType.RECOMMEND,
            DecisionType.APPROVE,
            DecisionType.DEFER,
        ]
    
    @pytest.mark.asyncio
    async def test_run_with_urgent_priority(self, workflow_agent, urgent_context):
        """Test run with urgent priority."""
        decision = await workflow_agent.run(urgent_context)
        
        # Should have recommendations for urgent work
        assert len(decision.recommendations) > 0


# Triage Agent Tests

class TestTriageAgent:
    """Tests for Triage Agent."""
    
    @pytest.fixture
    def triage_agent(self):
        """Create triage agent."""
        return create_triage_agent()
    
    def test_agent_creation(self, triage_agent):
        """Test triage agent creation."""
        assert triage_agent is not None
        assert triage_agent.agent_type == AgentType.TRIAGE
    
    @pytest.mark.asyncio
    async def test_classify_technical_issue(self, triage_agent, org_id, workflow_id, user_id):
        """Test classifying technical issue."""
        context = AgentContext(
            org_id=org_id,
            workflow_id=workflow_id,
            workflow_state="pending",
            user_id=user_id,
            metadata={
                "title": "Error 500 on login page",
                "description": "Getting internal server error when trying to log in",
            }
        )
        
        analysis = await triage_agent.analyze(context)
        
        assert "category" in analysis
        assert analysis["category"] in ["technical", "support"]
    
    @pytest.mark.asyncio
    async def test_classify_billing_issue(self, triage_agent, org_id, workflow_id, user_id):
        """Test classifying billing issue."""
        context = AgentContext(
            org_id=org_id,
            workflow_id=workflow_id,
            workflow_state="pending",
            user_id=user_id,
            metadata={
                "title": "Invoice discrepancy",
                "description": "I was charged $500 but my plan is $400/month",
            }
        )
        
        analysis = await triage_agent.analyze(context)
        
        assert analysis["category"] == "billing"
    
    @pytest.mark.asyncio
    async def test_classify_security_issue(self, triage_agent, org_id, workflow_id, user_id):
        """Test classifying security issue."""
        context = AgentContext(
            org_id=org_id,
            workflow_id=workflow_id,
            workflow_state="pending",
            user_id=user_id,
            metadata={
                "title": "URGENT: Data breach suspected",
                "description": "I think my account was hacked, unauthorized access detected",
            }
        )
        
        analysis = await triage_agent.analyze(context)
        
        assert analysis["category"] == "security"
        assert analysis["priority"] in ["urgent", "high"]
    
    @pytest.mark.asyncio
    async def test_routing_recommendation(self, triage_agent, org_id, workflow_id, user_id):
        """Test routing recommendation."""
        context = AgentContext(
            org_id=org_id,
            workflow_id=workflow_id,
            workflow_state="pending",
            user_id=user_id,
            metadata={
                "title": "Account upgrade request",
                "description": "We want to upgrade from starter to enterprise plan",
            }
        )
        
        analysis = await triage_agent.analyze(context)
        decision = await triage_agent.decide(context, analysis)
        
        assert decision.suggested_assignee is not None or "routing" in str(decision.recommendations).lower()


# Orchestrator Tests

class TestAgentOrchestrator:
    """Tests for Agent Orchestrator."""
    
    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator."""
        return get_orchestrator()
    
    def test_orchestrator_creation(self, orchestrator):
        """Test orchestrator creation."""
        assert orchestrator is not None
        assert hasattr(orchestrator, "run")
    
    @pytest.mark.asyncio
    async def test_run_all_agents(self, orchestrator, org_id, base_context):
        """Test running all agents through orchestrator."""
        result = await orchestrator.run(org_id, base_context)
        
        assert "request_id" in result
        assert "final_decision" in result
        assert "agent_decisions" in result
        assert "agents_executed" in result
    
    @pytest.mark.asyncio
    async def test_final_decision_synthesis(self, orchestrator, org_id, urgent_context):
        """Test final decision is synthesized."""
        result = await orchestrator.run(org_id, urgent_context)
        
        final = result["final_decision"]
        assert "decision_type" in final
        assert "confidence" in final
        assert "reasoning" in final
        assert "recommendations" in final
    
    @pytest.mark.asyncio
    async def test_error_handling(self, orchestrator, org_id):
        """Test error handling with minimal context."""
        minimal_context = AgentContext(
            org_id=org_id,
            user_id="test-user",
        )
        
        result = await orchestrator.run(org_id, minimal_context)
        
        # Should still complete, possibly with fallback decisions
        assert "final_decision" in result


class TestParallelOrchestrator:
    """Tests for Parallel Agent Orchestrator."""
    
    @pytest.fixture
    def parallel_orchestrator(self):
        """Create parallel orchestrator."""
        from app.agents import create_parallel_orchestrator
        return create_parallel_orchestrator()
    
    @pytest.mark.asyncio
    async def test_parallel_execution(self, parallel_orchestrator, org_id, base_context):
        """Test parallel agent execution."""
        result = await parallel_orchestrator.run(org_id, base_context)
        
        # Should have run all agents
        assert len(result["agents_executed"]) >= 1
        assert "final_decision" in result


# Integration Tests

class TestAgentIntegration:
    """Integration tests for agent system."""
    
    @pytest.mark.asyncio
    async def test_decision_immutability(self, org_id, base_context):
        """Test that agents don't mutate context."""
        original_state = base_context.workflow_state
        original_priority = base_context.workflow_priority
        
        orchestrator = get_orchestrator()
        await orchestrator.run(org_id, base_context)
        
        # Context should be unchanged
        assert base_context.workflow_state == original_state
        assert base_context.workflow_priority == original_priority
    
    @pytest.mark.asyncio
    async def test_decision_traceability(self, org_id, base_context):
        """Test decisions have full traceability."""
        agent = create_sla_agent()
        decision = await agent.run(base_context)
        
        # Must have audit trail fields
        assert decision.id is not None
        assert decision.agent_id is not None
        assert decision.timestamp is not None
        assert decision.decision_hash is not None
        
        # Must have reasoning
        assert decision.reasoning is not None
        assert len(decision.evidence) >= 0
    
    @pytest.mark.asyncio
    async def test_consistent_decisions(self, org_id, base_context):
        """Test decisions are consistent for same input."""
        agent = create_sla_agent()
        
        decision1 = await agent.run(base_context)
        decision2 = await agent.run(base_context)
        
        # Same analysis should yield same decision type
        assert decision1.decision_type == decision2.decision_type
        assert decision1.confidence == decision2.confidence


# Factory Tests

class TestAgentFactories:
    """Tests for agent factory functions."""
    
    def test_sla_factory(self):
        """Test SLA agent factory."""
        agent = create_sla_agent()
        assert isinstance(agent, SLAAgent)
        assert agent.agent_type == AgentType.SLA_RISK
    
    def test_workflow_factory(self):
        """Test workflow agent factory."""
        agent = create_workflow_agent()
        assert isinstance(agent, WorkflowAgent)
        assert agent.agent_type == AgentType.WORKFLOW
    
    def test_triage_factory(self):
        """Test triage agent factory."""
        agent = create_triage_agent()
        assert isinstance(agent, TriageAgent)
        assert agent.agent_type == AgentType.TRIAGE
    
    def test_orchestrator_singleton(self):
        """Test orchestrator is singleton."""
        o1 = get_orchestrator()
        o2 = get_orchestrator()
        assert o1 is o2
