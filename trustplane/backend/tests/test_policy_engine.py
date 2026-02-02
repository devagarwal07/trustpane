"""
Policy Engine Tests

Comprehensive tests for the Rego-compatible policy engine.
Tests cover RBAC, ABAC, workflow transitions, SLA policies, and agent decisions.
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from app.engines.policy_engine import (
    PolicyEngine,
    PolicyInput,
    PolicyResult,
    PolicyDecision,
    PolicyEffect,
    Policy,
    ROLE_HIERARCHY,
)


# =====================================================
# Fixtures
# =====================================================

@pytest.fixture
def engine():
    """Create a fresh policy engine for each test."""
    return PolicyEngine()


@pytest.fixture
def admin_user():
    """Admin user context."""
    return {"id": str(uuid4()), "role": "admin"}


@pytest.fixture
def manager_user():
    """Manager user context."""
    return {"id": str(uuid4()), "role": "manager"}


@pytest.fixture
def regular_user():
    """Regular user context."""
    return {"id": str(uuid4()), "role": "user"}


@pytest.fixture
def viewer_user():
    """Viewer user context."""
    return {"id": str(uuid4()), "role": "viewer"}


@pytest.fixture
def basic_policies():
    """Basic set of RBAC policies."""
    return [
        {
            "id": str(uuid4()),
            "name": "admin_full_access",
            "description": "Admins have full access",
            "effect": "allow",
            "type": "rbac",
            "role": "admin",
            "actions": ["*"],
            "resources": ["*"],
            "conditions": {},
            "priority": 1,
        },
        {
            "id": str(uuid4()),
            "name": "manager_workflow_access",
            "description": "Managers can manage workflows",
            "effect": "allow",
            "type": "rbac",
            "role": "manager",
            "actions": ["workflow:*"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        },
        {
            "id": str(uuid4()),
            "name": "user_read_access",
            "description": "Users can read",
            "effect": "allow",
            "type": "rbac",
            "role": "user",
            "actions": ["workflow:read", "sla:read"],
            "resources": ["*"],
            "conditions": {},
            "priority": 20,
        },
        {
            "id": str(uuid4()),
            "name": "viewer_read_only",
            "description": "Viewers can only read",
            "effect": "allow",
            "type": "rbac",
            "role": "viewer",
            "actions": ["workflow:read", "sla:read"],
            "resources": ["*"],
            "conditions": {},
            "priority": 30,
        },
    ]


# =====================================================
# Basic Policy Evaluation Tests
# =====================================================

class TestBasicPolicyEvaluation:
    """Tests for basic policy evaluation."""
    
    def test_default_deny(self, engine):
        """Test that default decision is deny when no policies match."""
        engine.load_policies([])
        
        input_data = PolicyInput(
            user={"id": "user1", "role": "viewer"},
            action="workflow:create",
            resource="workflow:123",
        )
        
        result = engine.evaluate(input_data)
        
        assert result.allowed is False
        assert result.decision == PolicyDecision.DENY
        assert "No matching policy found" in result.reasons[0]
    
    def test_simple_allow(self, engine, basic_policies, admin_user):
        """Test simple allow policy."""
        engine.load_policies(basic_policies)
        
        input_data = PolicyInput(
            user=admin_user,
            action="workflow:create",
            resource="workflow:123",
        )
        
        result = engine.evaluate(input_data)
        
        assert result.allowed is True
        assert result.decision == PolicyDecision.ALLOW
        assert "admin_full_access" in result.matched_policies
    
    def test_deny_override(self, engine, admin_user):
        """Test that deny overrides allow."""
        policies = [
            {
                "id": str(uuid4()),
                "name": "allow_all",
                "description": "Allow everything",
                "effect": "allow",
                "type": "abac",
                "actions": ["*"],
                "resources": ["*"],
                "conditions": {},
                "priority": 10,
            },
            {
                "id": str(uuid4()),
                "name": "deny_delete",
                "description": "Deny delete operations",
                "effect": "deny",
                "type": "abac",
                "actions": ["*:delete"],
                "resources": ["*"],
                "conditions": {},
                "priority": 1,
            },
        ]
        
        engine.load_policies(policies)
        
        # Create should be allowed
        result = engine.evaluate(PolicyInput(
            user=admin_user,
            action="workflow:create",
            resource="workflow:123",
        ))
        assert result.allowed is True
        
        # Delete should be denied
        result = engine.evaluate(PolicyInput(
            user=admin_user,
            action="workflow:delete",
            resource="workflow:123",
        ))
        assert result.allowed is False
        assert "deny_delete" in result.matched_policies


# =====================================================
# RBAC Tests
# =====================================================

class TestRBAC:
    """Tests for Role-Based Access Control."""
    
    def test_role_hierarchy(self):
        """Test role hierarchy definition."""
        assert "admin" in ROLE_HIERARCHY
        assert "manager" in ROLE_HIERARCHY["admin"]
        assert "user" in ROLE_HIERARCHY["admin"]
        assert "viewer" in ROLE_HIERARCHY["admin"]
    
    def test_admin_has_all_access(self, engine, basic_policies, admin_user):
        """Test admin has access to everything."""
        engine.load_policies(basic_policies)
        
        actions = [
            "workflow:create",
            "workflow:read",
            "workflow:update",
            "workflow:delete",
            "sla:create",
            "policy:create",
        ]
        
        for action in actions:
            result = engine.evaluate(PolicyInput(
                user=admin_user,
                action=action,
                resource="*",
            ))
            assert result.allowed is True, f"Admin should have access to {action}"
    
    def test_manager_limited_access(self, engine, basic_policies, manager_user):
        """Test manager has limited access."""
        engine.load_policies(basic_policies)
        
        # Should have workflow access
        result = engine.evaluate(PolicyInput(
            user=manager_user,
            action="workflow:create",
            resource="workflow:123",
        ))
        assert result.allowed is True
        
        # Should not have policy access (not in manager's policies)
        result = engine.evaluate(PolicyInput(
            user=manager_user,
            action="policy:create",
            resource="policy:123",
        ))
        assert result.allowed is False
    
    def test_viewer_read_only(self, engine, basic_policies, viewer_user):
        """Test viewer has read-only access."""
        engine.load_policies(basic_policies)
        
        # Should have read access
        result = engine.evaluate(PolicyInput(
            user=viewer_user,
            action="workflow:read",
            resource="workflow:123",
        ))
        assert result.allowed is True
        
        # Should not have write access
        result = engine.evaluate(PolicyInput(
            user=viewer_user,
            action="workflow:create",
            resource="workflow:123",
        ))
        assert result.allowed is False


# =====================================================
# ABAC Tests
# =====================================================

class TestABAC:
    """Tests for Attribute-Based Access Control."""
    
    def test_condition_eq(self, engine, regular_user):
        """Test equality condition."""
        policies = [{
            "id": str(uuid4()),
            "name": "department_access",
            "description": "Users can access their department resources",
            "effect": "allow",
            "type": "abac",
            "actions": ["*"],
            "resources": ["*"],
            "conditions": {
                "department": {"operator": "eq", "value": "engineering"},
            },
            "priority": 10,
        }]
        
        engine.load_policies(policies)
        
        # Matching department
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:read",
            resource="workflow:123",
            context={"department": "engineering"},
        ))
        assert result.allowed is True
        
        # Non-matching department
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:read",
            resource="workflow:123",
            context={"department": "sales"},
        ))
        assert result.allowed is False
    
    def test_condition_in(self, engine, regular_user):
        """Test 'in' condition operator."""
        policies = [{
            "id": str(uuid4()),
            "name": "allowed_regions",
            "description": "Access only from allowed regions",
            "effect": "allow",
            "type": "abac",
            "actions": ["*"],
            "resources": ["*"],
            "conditions": {
                "region": {"operator": "in", "value": ["us-east", "us-west", "eu-west"]},
            },
            "priority": 10,
        }]
        
        engine.load_policies(policies)
        
        # Allowed region
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:read",
            resource="workflow:123",
            context={"region": "us-east"},
        ))
        assert result.allowed is True
        
        # Disallowed region
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:read",
            resource="workflow:123",
            context={"region": "ap-south"},
        ))
        assert result.allowed is False
    
    def test_condition_gt(self, engine, regular_user):
        """Test 'greater than' condition operator."""
        policies = [{
            "id": str(uuid4()),
            "name": "senior_access",
            "description": "Only users with > 1 year tenure",
            "effect": "allow",
            "type": "abac",
            "actions": ["sensitive:*"],
            "resources": ["*"],
            "conditions": {
                "tenure_years": {"operator": "gt", "value": 1},
            },
            "priority": 10,
        }]
        
        engine.load_policies(policies)
        
        # Senior user
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="sensitive:read",
            resource="doc:123",
            context={"tenure_years": 3},
        ))
        assert result.allowed is True
        
        # New user
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="sensitive:read",
            resource="doc:123",
            context={"tenure_years": 0.5},
        ))
        assert result.allowed is False
    
    def test_variable_reference(self, engine, regular_user):
        """Test variable reference in conditions."""
        user_id = regular_user["id"]
        
        policies = [{
            "id": str(uuid4()),
            "name": "own_resource_access",
            "description": "Users can access their own resources",
            "effect": "allow",
            "type": "abac",
            "actions": ["*"],
            "resources": ["*"],
            "conditions": {
                "resource_owner": {"operator": "eq", "value": "${user.id}"},
            },
            "priority": 10,
        }]
        
        engine.load_policies(policies)
        
        # Own resource
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:update",
            resource="workflow:123",
            context={"resource_owner": user_id},
        ))
        assert result.allowed is True
        
        # Other's resource
        result = engine.evaluate(PolicyInput(
            user=regular_user,
            action="workflow:update",
            resource="workflow:123",
            context={"resource_owner": str(uuid4())},
        ))
        assert result.allowed is False


# =====================================================
# Pattern Matching Tests
# =====================================================

class TestPatternMatching:
    """Tests for wildcard pattern matching."""
    
    def test_exact_match(self, engine):
        """Test exact pattern match."""
        assert engine._matches_pattern(["workflow:create"], "workflow:create")
        assert not engine._matches_pattern(["workflow:create"], "workflow:read")
    
    def test_wildcard_suffix(self, engine):
        """Test wildcard at end of pattern."""
        assert engine._matches_pattern(["workflow:*"], "workflow:create")
        assert engine._matches_pattern(["workflow:*"], "workflow:read")
        assert not engine._matches_pattern(["workflow:*"], "sla:create")
    
    def test_wildcard_prefix(self, engine):
        """Test wildcard at start of pattern."""
        assert engine._matches_pattern(["*:read"], "workflow:read")
        assert engine._matches_pattern(["*:read"], "sla:read")
        assert not engine._matches_pattern(["*:read"], "workflow:create")
    
    def test_full_wildcard(self, engine):
        """Test full wildcard."""
        assert engine._matches_pattern(["*"], "workflow:create")
        assert engine._matches_pattern(["*"], "anything")


# =====================================================
# Workflow Transition Tests
# =====================================================

class TestWorkflowTransition:
    """Tests for workflow transition policy evaluation."""
    
    def test_valid_transition(self, engine, admin_user):
        """Test valid workflow state transition."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_transitions",
            "description": "Allow workflow transitions",
            "effect": "allow",
            "type": "workflow",
            "actions": ["workflow:transition"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        result = engine.evaluate_workflow_transition(
            user=admin_user,
            workflow={"id": str(uuid4()), "current_state": "pending"},
            to_state="active",
        )
        
        assert result.allowed is True
    
    def test_invalid_transition(self, engine, admin_user):
        """Test invalid workflow state transition."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_transitions",
            "description": "Allow workflow transitions",
            "effect": "allow",
            "type": "workflow",
            "actions": ["workflow:transition"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        # Can't go from pending directly to completed
        result = engine.evaluate_workflow_transition(
            user=admin_user,
            workflow={"id": str(uuid4()), "current_state": "pending"},
            to_state="completed",
        )
        
        assert result.allowed is False
        assert "Invalid transition" in str(result.reasons)
    
    def test_transition_reason_required(self, engine, admin_user):
        """Test transition requiring reason."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_transitions",
            "description": "Allow workflow transitions",
            "effect": "allow",
            "type": "workflow",
            "actions": ["workflow:transition"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        # Cancellation without reason should fail
        result = engine.evaluate_workflow_transition(
            user=admin_user,
            workflow={"id": str(uuid4()), "current_state": "active"},
            to_state="cancelled",
        )
        
        assert result.allowed is False
        assert "Reason required" in str(result.reasons)
        
        # With reason should pass
        result = engine.evaluate_workflow_transition(
            user=admin_user,
            workflow={"id": str(uuid4()), "current_state": "active"},
            to_state="cancelled",
            reason="Customer requested cancellation of the order",
        )
        
        assert result.allowed is True


# =====================================================
# SLA Policy Tests
# =====================================================

class TestSLAPolicy:
    """Tests for SLA policy evaluation."""
    
    def test_escalation_levels(self, engine):
        """Test SLA escalation level determination."""
        # Critical: hard breach + p1
        assert engine._get_escalation_level({
            "status": "hard_breach",
            "priority": "p1",
        }) == "critical"
        
        # High: hard breach + p2
        assert engine._get_escalation_level({
            "status": "hard_breach",
            "priority": "p2",
        }) == "high"
        
        # Medium: soft breach + p1/p2
        assert engine._get_escalation_level({
            "status": "soft_breach",
            "priority": "p1",
        }) == "medium"
        
        # Low: soft breach + p3
        assert engine._get_escalation_level({
            "status": "soft_breach",
            "priority": "p3",
        }) == "low"
        
        # None: active
        assert engine._get_escalation_level({
            "status": "active",
            "priority": "p1",
        }) == "none"
    
    def test_sla_recommendations(self, engine):
        """Test SLA recommendation generation."""
        # Hard breach recommendations
        recs = engine._get_sla_recommendations({
            "status": "hard_breach",
            "priority": "p1",
            "elapsed_minutes": 120,
            "soft_limit": 60,
            "hard_limit": 90,
        })
        
        assert "Immediate manager notification required" in recs
        assert "Reassign to available senior staff" in recs
        
        # Approaching soft breach
        recs = engine._get_sla_recommendations({
            "status": "active",
            "priority": "p3",
            "elapsed_minutes": 50,
            "soft_limit": 60,
            "hard_limit": 120,
        })
        
        assert "Approaching soft breach threshold" in recs[0]


# =====================================================
# Agent Decision Tests
# =====================================================

class TestAgentDecision:
    """Tests for AI agent decision policy evaluation."""
    
    def test_forbidden_actions(self, engine):
        """Test that agents cannot perform certain actions directly."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_agent",
            "description": "Allow agent actions",
            "effect": "allow",
            "type": "agent",
            "actions": ["agent:*"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        # Direct transition should be denied
        result = engine.evaluate_agent_decision(
            agent={
                "id": "agent-1",
                "action": "workflow:transition",
                "confidence": 0.95,
                "reasoning": "This workflow should be transitioned to completed state.",
            },
            action="workflow:transition",
        )
        
        assert result.allowed is False
        assert "Agent cannot directly perform" in str(result.reasons)
    
    def test_confidence_threshold(self, engine):
        """Test agent confidence threshold."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_agent",
            "description": "Allow agent actions",
            "effect": "allow",
            "type": "agent",
            "actions": ["agent:*"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        # Low confidence should be denied
        result = engine.evaluate_agent_decision(
            agent={
                "id": "agent-1",
                "action": "recommend_transition",
                "confidence": 0.5,
                "reasoning": "This workflow might need transition but I'm not sure.",
            },
            action="recommend_transition",
        )
        
        assert result.allowed is False
        assert "below threshold" in str(result.reasons)
    
    def test_reasoning_requirement(self, engine):
        """Test that agents must provide reasoning."""
        engine.load_policies([{
            "id": str(uuid4()),
            "name": "allow_agent",
            "description": "Allow agent actions",
            "effect": "allow",
            "type": "agent",
            "actions": ["agent:*"],
            "resources": ["*"],
            "conditions": {},
            "priority": 10,
        }])
        
        # No reasoning should be denied
        result = engine.evaluate_agent_decision(
            agent={
                "id": "agent-1",
                "action": "recommend_transition",
                "confidence": 0.95,
                "reasoning": "Short",  # Too short
            },
            action="recommend_transition",
        )
        
        assert result.allowed is False
        assert "reasoning" in str(result.reasons).lower()
    
    def test_human_approval_required(self, engine):
        """Test human approval requirement for certain decisions."""
        input_data = PolicyInput(
            user={"id": "system:agent", "role": "agent"},
            action="agent:recommend_transition",
            resource="agent:decision",
            context={},
            workflow={"id": str(uuid4()), "current_state": "active"},
            agent={
                "id": "agent-1",
                "action": "recommend_transition",
                "confidence": 0.9,  # Below 0.95 threshold
            },
        )
        
        assert engine._check_human_approval_required(input_data) is True


# =====================================================
# Performance Tests
# =====================================================

class TestPerformance:
    """Tests for policy evaluation performance."""
    
    def test_evaluation_time_tracked(self, engine, basic_policies, admin_user):
        """Test that evaluation time is tracked."""
        engine.load_policies(basic_policies)
        
        result = engine.evaluate(PolicyInput(
            user=admin_user,
            action="workflow:create",
            resource="workflow:123",
        ))
        
        assert result.evaluation_time_ms >= 0
        assert result.evaluation_time_ms < 100  # Should be fast
    
    def test_input_hash_generated(self, engine, basic_policies, admin_user):
        """Test that input hash is generated for audit."""
        engine.load_policies(basic_policies)
        
        result = engine.evaluate(PolicyInput(
            user=admin_user,
            action="workflow:create",
            resource="workflow:123",
        ))
        
        assert result.input_hash
        assert len(result.input_hash) == 64  # SHA-256 hex


# =====================================================
# Legacy Compatibility Tests
# =====================================================

class TestLegacyCompatibility:
    """Tests for backward compatibility with legacy API."""
    
    def test_legacy_evaluate_policies(self, engine, basic_policies):
        """Test legacy evaluate_policies method."""
        allowed, reasons, matched_ids = engine.evaluate_policies(
            policies=basic_policies,
            action="workflow:create",
            resource="workflow:123",
            context={"user_id": str(uuid4()), "user_role": "admin"},
        )
        
        assert allowed is True
        assert len(reasons) > 0
    
    def test_legacy_get_effective_permissions(self, engine, basic_policies):
        """Test legacy get_effective_permissions method."""
        permissions = engine.get_effective_permissions(
            policies=basic_policies,
            user_id=str(uuid4()),
            user_role="manager",
        )
        
        # Manager should have workflow permissions
        assert any("workflow" in p for p in permissions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
