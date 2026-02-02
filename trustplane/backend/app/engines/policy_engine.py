"""
Policy Engine (Rego-Compatible)

This module implements the core policy evaluation logic for TrustPlane.
It provides a Python-native Rego-compatible policy engine that supports:

1. RBAC (Role-Based Access Control)
2. ABAC (Attribute-Based Access Control)  
3. Workflow transition policies
4. SLA enforcement policies
5. AI Agent decision boundaries

Why not use OPA directly?
=========================
1. Reduced complexity: No sidecar/microservice needed
2. Better integration: Native Python with async support
3. Auditability: Every evaluation logged in our event ledger
4. Flexibility: Custom operators for our domain (workflows, SLAs)

The engine is Rego-COMPATIBLE meaning:
- Same policy semantics (deny-override, set-based evaluation)
- Same condition operators
- Same wildcard patterns
- Policies can be migrated to OPA if needed later
"""

from typing import Any
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field
from uuid import UUID
import re
import fnmatch
import hashlib
import json


class PolicyEffect(str, Enum):
    """Policy effect type."""
    ALLOW = "allow"
    DENY = "deny"


class PolicyDecision(str, Enum):
    """Policy evaluation decision."""
    ALLOW = "allow"
    DENY = "deny"
    NOT_APPLICABLE = "not_applicable"


class PolicyType(str, Enum):
    """Types of policies."""
    RBAC = "rbac"
    ABAC = "abac"
    WORKFLOW = "workflow"
    SLA = "sla"
    AGENT = "agent"
    AUDIT = "audit"


@dataclass
class PolicyInput:
    """
    Structured input for policy evaluation.
    Mirrors Rego input object.
    """
    user: dict[str, Any]
    action: str
    resource: str
    context: dict[str, Any] = field(default_factory=dict)
    
    # Optional domain-specific inputs
    workflow: dict[str, Any] | None = None
    sla: dict[str, Any] | None = None
    agent: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for evaluation."""
        result = {
            "user": self.user,
            "action": self.action,
            "resource": self.resource,
            "context": self.context,
        }
        if self.workflow:
            result["workflow"] = self.workflow
            result["requested_state"] = self.context.get("requested_state")
            result["reason"] = self.context.get("reason")
        if self.sla:
            result["sla"] = self.sla
            result["pause_reason"] = self.context.get("pause_reason")
        if self.agent:
            result["agent"] = self.agent
        return result


@dataclass
class PolicyResult:
    """
    Result of policy evaluation.
    Provides full audit trail.
    """
    decision: PolicyDecision
    allowed: bool
    reasons: list[str]
    matched_policies: list[str]
    evaluation_time_ms: float
    input_hash: str  # SHA-256 of input for audit
    timestamp: str
    
    # Domain-specific results
    escalation_level: str | None = None
    recommended_actions: list[str] = field(default_factory=list)
    requires_human_approval: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/API response."""
        return {
            "decision": self.decision.value,
            "allowed": self.allowed,
            "reasons": self.reasons,
            "matched_policies": self.matched_policies,
            "evaluation_time_ms": self.evaluation_time_ms,
            "input_hash": self.input_hash,
            "timestamp": self.timestamp,
            "escalation_level": self.escalation_level,
            "recommended_actions": self.recommended_actions,
            "requires_human_approval": self.requires_human_approval,
        }


class RegoOperator(str, Enum):
    """Supported condition operators (Rego-compatible)."""
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    MATCHES = "matches"  # Regex
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


# Role hierarchy for RBAC
ROLE_HIERARCHY: dict[str, list[str]] = {
    "admin": ["manager", "user", "viewer"],
    "manager": ["user", "viewer"],
    "user": ["viewer"],
    "viewer": [],
}


@dataclass
class Policy:
    """Policy definition for evaluation."""
    id: str
    name: str
    description: str
    effect: PolicyEffect
    actions: list[str]
    resources: list[str]
    conditions: dict[str, Any]
    priority: int
    type: str = "abac"
    role: str | None = None
    is_system: bool = False


class PolicyEngine:
    """
    Rego-Compatible Policy Engine.
    
    Evaluation Semantics:
    ====================
    1. Collect all applicable policies (matching action/resource)
    2. Sort by priority (lower = higher priority)
    3. Evaluate conditions against context
    4. Apply deny-override: ANY deny → denied
    5. If no deny and ANY allow → allowed
    6. Default: denied
    
    Thread Safety:
    =============
    The engine is stateless per-evaluation.
    Policies are loaded once and immutable during evaluation.
    """
    
    def __init__(self):
        self.policies: list[Policy] = []
        self._policy_cache: dict[str, list[Policy]] = {}
    
    def load_policies(self, policies: list[Policy | dict]) -> None:
        """Load policies into the engine, sorted by priority."""
        converted = []
        for p in policies:
            if isinstance(p, dict):
                converted.append(Policy(
                    id=str(p.get("id", "")),
                    name=p.get("name", ""),
                    description=p.get("description", ""),
                    effect=PolicyEffect(p.get("effect", "deny")),
                    actions=p.get("actions", []),
                    resources=p.get("resources", ["*"]),
                    conditions=p.get("conditions", {}),
                    priority=p.get("priority", 100),
                    type=p.get("type", "abac"),
                    role=p.get("role"),
                    is_system=p.get("is_system", False),
                ))
            else:
                converted.append(p)
        
        self.policies = sorted(converted, key=lambda p: p.priority)
        self._policy_cache.clear()
        self._build_policy_cache()
    
    def _build_policy_cache(self) -> None:
        """Build action-based cache for faster lookup."""
        for policy in self.policies:
            for action_pattern in policy.actions:
                if action_pattern not in self._policy_cache:
                    self._policy_cache[action_pattern] = []
                self._policy_cache[action_pattern].append(policy)
    
    def evaluate(self, input_data: PolicyInput) -> PolicyResult:
        """
        Main evaluation entry point.
        
        This is the Rego-equivalent of:
            allow { ... }
            deny { ... }
        """
        start_time = datetime.now(timezone.utc)
        
        # Hash input for audit trail
        input_dict = input_data.to_dict()
        input_hash = hashlib.sha256(
            json.dumps(input_dict, sort_keys=True, default=str).encode()
        ).hexdigest()
        
        # Collect matching policies
        matching_allows: list[Policy] = []
        matching_denies: list[Policy] = []
        allow_reasons: list[str] = []
        deny_reasons: list[str] = []
        
        # Build evaluation context
        context = self._build_context(input_data)
        
        for policy in self.policies:
            match_result = self._evaluate_policy(policy, input_data, context)
            
            if match_result is None:
                continue  # Policy not applicable
            
            if policy.effect == PolicyEffect.DENY:
                matching_denies.append(policy)
                deny_reasons.append(f"Denied by policy: {policy.name}")
            else:
                matching_allows.append(policy)
                allow_reasons.append(f"Allowed by policy: {policy.name}")
        
        # Determine decision (deny-override semantics)
        if matching_denies:
            decision = PolicyDecision.DENY
            allowed = False
            reasons = deny_reasons
        elif matching_allows:
            decision = PolicyDecision.ALLOW
            allowed = True
            reasons = allow_reasons
        else:
            decision = PolicyDecision.DENY
            allowed = False
            reasons = ["No matching policy found - default deny"]
        
        # Calculate evaluation time
        end_time = datetime.now(timezone.utc)
        eval_time_ms = (end_time - start_time).total_seconds() * 1000
        
        # Build result with domain-specific data
        result = PolicyResult(
            decision=decision,
            allowed=allowed,
            reasons=reasons,
            matched_policies=[p.name for p in matching_allows + matching_denies],
            evaluation_time_ms=eval_time_ms,
            input_hash=input_hash,
            timestamp=start_time.isoformat(),
        )
        
        # Add domain-specific results
        if input_data.sla:
            result.escalation_level = self._get_escalation_level(input_data.sla)
            result.recommended_actions = self._get_sla_recommendations(input_data.sla)
        
        if input_data.agent:
            result.requires_human_approval = self._check_human_approval_required(
                input_data
            )
        
        return result
    
    def _build_context(self, input_data: PolicyInput) -> dict[str, Any]:
        """Build full evaluation context."""
        now = datetime.now(timezone.utc)
        
        context = {
            **input_data.context,
            "user_id": input_data.user.get("id"),
            "user_role": input_data.user.get("role"),
            "timestamp": now.isoformat(),
            "hour_of_day": now.hour,
            "day_of_week": now.weekday(),
            "is_business_hours": 9 <= now.hour < 17 and now.weekday() < 5,
            "is_business_day": now.weekday() < 5,
        }
        
        # Add effective roles (with hierarchy)
        user_role = input_data.user.get("role", "viewer")
        effective_roles = self._get_effective_roles(user_role)
        context["effective_roles"] = effective_roles
        
        return context
    
    def _get_effective_roles(self, role: str) -> list[str]:
        """Get all effective roles including inherited ones."""
        roles = [role]
        inherited = ROLE_HIERARCHY.get(role, [])
        roles.extend(inherited)
        return roles
    
    def _evaluate_policy(
        self,
        policy: Policy,
        input_data: PolicyInput,
        context: dict[str, Any],
    ) -> bool | None:
        """
        Evaluate a single policy.
        
        Returns:
            True if policy matches and grants/denies
            None if policy doesn't apply
        """
        # Check action match
        if not self._matches_pattern(policy.actions, input_data.action):
            return None
        
        # Check resource match
        if not self._matches_pattern(policy.resources, input_data.resource):
            return None
        
        # Check role match for RBAC policies
        if policy.type == "rbac" and policy.role:
            if policy.role not in context.get("effective_roles", []):
                return None
        
        # Check conditions
        if policy.conditions:
            if not self._evaluate_conditions(policy.conditions, context, input_data):
                return None
        
        return True
    
    def _matches_pattern(self, patterns: list[str], value: str) -> bool:
        """
        Check if value matches any pattern.
        Supports:
        - Exact match: "workflow:create"
        - Wildcard: "workflow:*"
        - Multi-wildcard: "*:read"
        - Full wildcard: "*"
        """
        for pattern in patterns:
            if pattern == "*":
                return True
            if pattern == value:
                return True
            if "*" in pattern:
                # Convert to regex pattern
                regex_pattern = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
                if re.match(regex_pattern, value):
                    return True
            # Also support fnmatch-style patterns
            if fnmatch.fnmatch(value, pattern):
                return True
        return False
    
    def _evaluate_conditions(
        self,
        conditions: dict[str, Any],
        context: dict[str, Any],
        input_data: PolicyInput,
    ) -> bool:
        """
        Evaluate all conditions (AND semantics).
        All conditions must be true for the policy to apply.
        """
        for key, expected in conditions.items():
            # Resolve variable references like ${user.id}
            if isinstance(expected, dict):
                value = expected.get("value")
                if isinstance(value, str) and value.startswith("${"):
                    value = self._resolve_variable(value, context, input_data)
                    expected = {**expected, "value": value}
            elif isinstance(expected, str) and expected.startswith("${"):
                expected = self._resolve_variable(expected, context, input_data)
            
            # Get actual value from context
            actual = self._get_nested_value(context, key)
            if actual is None:
                actual = self._get_nested_value(input_data.to_dict(), key)
            
            # Apply operator
            if not self._apply_condition(expected, actual):
                return False
        
        return True
    
    def _resolve_variable(
        self,
        var_ref: str,
        context: dict[str, Any],
        input_data: PolicyInput,
    ) -> Any:
        """Resolve ${path.to.value} style variable references."""
        # Extract path from ${...}
        path = var_ref[2:-1]  # Remove ${ and }
        
        # Try context first
        value = self._get_nested_value(context, path)
        if value is not None:
            return value
        
        # Try input data
        return self._get_nested_value(input_data.to_dict(), path)
    
    def _get_nested_value(self, obj: dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        parts = path.split(".")
        current = obj
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        
        return current
    
    def _apply_condition(self, expected: Any, actual: Any) -> bool:
        """Apply condition check."""
        if isinstance(expected, dict):
            operator = expected.get("operator", "eq")
            value = expected.get("value")
            return self._apply_operator(operator, actual, value)
        else:
            return actual == expected
    
    def _apply_operator(self, operator: str, actual: Any, value: Any) -> bool:
        """Apply comparison operator (Rego-compatible)."""
        try:
            if operator == "eq":
                return actual == value
            elif operator == "ne":
                return actual != value
            elif operator == "gt":
                return actual is not None and actual > value
            elif operator == "gte":
                return actual is not None and actual >= value
            elif operator == "lt":
                return actual is not None and actual < value
            elif operator == "lte":
                return actual is not None and actual <= value
            elif operator == "in":
                if isinstance(value, (list, tuple, set)):
                    return actual in value
                return False
            elif operator == "not_in":
                if isinstance(value, (list, tuple, set)):
                    return actual not in value
                return True
            elif operator == "contains":
                if isinstance(actual, str) and isinstance(value, str):
                    return value in actual
                if isinstance(actual, (list, tuple, set)):
                    return value in actual
                return False
            elif operator == "startswith":
                if isinstance(actual, str) and isinstance(value, str):
                    return actual.startswith(value)
                return False
            elif operator == "endswith":
                if isinstance(actual, str) and isinstance(value, str):
                    return actual.endswith(value)
                return False
            elif operator == "matches":
                if isinstance(actual, str) and isinstance(value, str):
                    return bool(re.match(value, actual))
                return False
            elif operator == "exists":
                return actual is not None
            elif operator == "not_exists":
                return actual is None
            else:
                return False
        except (TypeError, ValueError):
            return False
    
    # =====================================================
    # Domain-Specific Evaluation Methods
    # =====================================================
    
    def evaluate_workflow_transition(
        self,
        user: dict[str, Any],
        workflow: dict[str, Any],
        to_state: str,
        reason: str | None = None,
    ) -> PolicyResult:
        """
        Evaluate workflow transition policy.
        
        Rego equivalent:
            package trustplane.workflow
            allow_transition { ... }
        """
        input_data = PolicyInput(
            user=user,
            action="workflow:transition",
            resource=f"workflow:{workflow.get('id', '')}",
            context={
                "requested_state": to_state,
                "reason": reason,
            },
            workflow=workflow,
        )
        
        result = self.evaluate(input_data)
        
        # Additional workflow-specific checks
        valid_transitions = {
            "pending": ["active", "cancelled"],
            "active": ["paused", "completed", "failed", "cancelled"],
            "paused": ["active", "cancelled", "failed"],
            "completed": [],
            "failed": [],
            "cancelled": [],
        }
        
        current_state = workflow.get("current_state", "pending")
        allowed_states = valid_transitions.get(current_state, [])
        
        if to_state not in allowed_states:
            result.allowed = False
            result.decision = PolicyDecision.DENY
            result.reasons.append(
                f"Invalid transition: {current_state} → {to_state}"
            )
        
        # Check if reason is required
        reason_required_transitions = [
            ("active", "failed"),
            ("active", "cancelled"),
            ("paused", "failed"),
            ("paused", "cancelled"),
            ("pending", "cancelled"),
        ]
        
        if (current_state, to_state) in reason_required_transitions:
            if not reason or len(reason) < 10:
                result.allowed = False
                result.decision = PolicyDecision.DENY
                result.reasons.append(
                    "Reason required for this transition (min 10 chars)"
                )
        
        return result
    
    def evaluate_sla_action(
        self,
        user: dict[str, Any],
        sla: dict[str, Any],
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyResult:
        """
        Evaluate SLA-related policy.
        
        Rego equivalent:
            package trustplane.sla
            can_pause { ... }
        """
        context = context or {}
        
        input_data = PolicyInput(
            user=user,
            action=f"sla:{action}",
            resource=f"sla:{sla.get('id', '')}",
            context=context,
            sla=sla,
        )
        
        result = self.evaluate(input_data)
        
        # Add SLA-specific recommendations
        result.escalation_level = self._get_escalation_level(sla)
        result.recommended_actions = self._get_sla_recommendations(sla)
        
        return result
    
    def evaluate_agent_decision(
        self,
        agent: dict[str, Any],
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyResult:
        """
        Evaluate AI agent decision policy.
        
        Rego equivalent:
            package trustplane.agent
            agent_decision_allowed { ... }
        """
        context = context or {}
        
        # Agents use a system user context
        system_user = {
            "id": "system:agent",
            "role": "agent",
            "type": "ai_agent",
        }
        
        input_data = PolicyInput(
            user=system_user,
            action=f"agent:{action}",
            resource="agent:decision",
            context=context,
            agent=agent,
        )
        
        result = self.evaluate(input_data)
        
        # Agent-specific checks
        forbidden_actions = [
            "workflow:create",
            "workflow:delete", 
            "workflow:transition",
            "sla:create",
            "sla:delete",
            "policy:create",
            "policy:delete",
        ]
        
        if action in forbidden_actions:
            result.allowed = False
            result.decision = PolicyDecision.DENY
            result.reasons.append(f"Agent cannot directly perform: {action}")
        
        # Check confidence threshold
        confidence = agent.get("confidence", 0)
        if confidence < 0.8:
            result.allowed = False
            result.decision = PolicyDecision.DENY
            result.reasons.append(f"Confidence {confidence} below threshold 0.8")
        
        # Check reasoning requirement
        reasoning = agent.get("reasoning", "")
        if not reasoning or len(reasoning) < 20:
            result.allowed = False
            result.decision = PolicyDecision.DENY
            result.reasons.append("Agent must provide reasoning (min 20 chars)")
        
        # Determine if human approval needed
        result.requires_human_approval = self._check_human_approval_required(
            input_data
        )
        
        return result
    
    def _get_escalation_level(self, sla: dict[str, Any]) -> str:
        """Determine SLA escalation level."""
        status = sla.get("status", "active")
        priority = sla.get("priority", "p3")
        
        if status == "hard_breach" and priority == "p1":
            return "critical"
        elif status == "hard_breach" and priority == "p2":
            return "high"
        elif status == "soft_breach" and priority in ["p1", "p2"]:
            return "medium"
        elif status == "soft_breach":
            return "low"
        else:
            return "none"
    
    def _get_sla_recommendations(self, sla: dict[str, Any]) -> list[str]:
        """Get recommended actions for SLA."""
        recommendations = []
        status = sla.get("status", "active")
        priority = sla.get("priority", "p3")
        elapsed = sla.get("elapsed_minutes", 0)
        soft_limit = sla.get("soft_limit", 60)
        hard_limit = sla.get("hard_limit", 120)
        
        if status == "hard_breach":
            recommendations.append("Immediate manager notification required")
            if priority in ["p1", "p2"]:
                recommendations.append("Reassign to available senior staff")
        
        if status == "active":
            if elapsed > soft_limit * 0.75:
                recommendations.append("Warning: Approaching soft breach threshold")
            if elapsed > hard_limit * 0.9:
                recommendations.append("Critical: Approaching hard breach threshold")
        
        return recommendations
    
    def _check_human_approval_required(self, input_data: PolicyInput) -> bool:
        """Check if human approval is required for agent decision."""
        if not input_data.agent:
            return False
        
        agent = input_data.agent
        action = agent.get("action", "")
        confidence = agent.get("confidence", 0)
        
        # Human approval required for certain actions
        if action == "recommend_transition":
            workflow = input_data.workflow or {}
            if workflow.get("current_state") in ["active", "paused"]:
                return True
        
        if action == "recommend_priority_change":
            return True
        
        # Low confidence requires human approval
        if confidence < 0.95:
            return True
        
        return False
    
    # =====================================================
    # Legacy Compatibility Methods
    # =====================================================
    
    def evaluate_policies(
        self,
        policies: list[dict[str, Any]],
        action: str,
        resource: str,
        context: dict[str, Any],
    ) -> tuple[bool, list[str], list[UUID]]:
        """
        Legacy evaluation method for backward compatibility.
        
        Returns:
            Tuple of (allowed: bool, reasons: list[str], matched_policy_ids: list[UUID])
        """
        # Load policies if provided
        if policies:
            self.load_policies(policies)
        
        # Create input
        user_id = context.get("user_id", "")
        user_role = context.get("user_role", "viewer")
        
        input_data = PolicyInput(
            user={"id": user_id, "role": user_role},
            action=action,
            resource=resource,
            context=context,
        )
        
        result = self.evaluate(input_data)
        
        # Get matched policy IDs
        matched_ids = []
        for policy in self.policies:
            if policy.name in result.matched_policies:
                try:
                    matched_ids.append(UUID(policy.id))
                except (ValueError, TypeError):
                    pass
        
        return result.allowed, result.reasons, matched_ids
    
    def get_effective_permissions(
        self,
        policies: list[dict[str, Any]] | None = None,
        user_id: str = "",
        user_role: str = "viewer",
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        """
        Get all permissions effectively granted to a user.
        
        Evaluates all allow policies and returns matching action patterns.
        """
        if policies:
            self.load_policies(policies)
        
        permissions: set[str] = set()
        context = context or {}
        
        effective_roles = self._get_effective_roles(user_role)
        context["effective_roles"] = effective_roles
        context["user_id"] = user_id
        context["user_role"] = user_role
        
        input_data = PolicyInput(
            user={"id": user_id, "role": user_role},
            action="*",
            resource="*",
            context=context,
        )
        
        for policy in self.policies:
            if policy.effect != PolicyEffect.ALLOW:
                continue
            
            # Check role match for RBAC
            if policy.type == "rbac" and policy.role:
                if policy.role not in effective_roles:
                    continue
            
            # Check conditions
            if policy.conditions:
                if not self._evaluate_conditions(
                    policy.conditions, context, input_data
                ):
                    continue
            
            # Add all actions from this policy
            for action in policy.actions:
                if "*" not in action:
                    permissions.add(action)
        
        return list(permissions)


# Singleton engine instance
policy_engine = PolicyEngine()


def get_policy_engine() -> PolicyEngine:
    """Get the singleton policy engine."""
    return policy_engine
