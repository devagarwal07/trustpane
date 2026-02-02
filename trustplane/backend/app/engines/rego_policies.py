"""
Rego Policy Definitions

This module contains the Rego policy templates and default policies
for TrustPlane. Rego is the policy language used by Open Policy Agent (OPA).

Why Rego?
=========
1. Declarative: Policies as code, version controlled
2. Expressive: Complex conditions in simple syntax
3. Auditable: Every decision can be traced to a rule
4. Standard: OPA is the de-facto standard for policy-as-code

Policy Categories:
==================
1. RBAC: Role-based access control
2. ABAC: Attribute-based access control
3. Workflow: Workflow transition rules
4. SLA: SLA enforcement rules
5. Agent: AI agent decision boundaries
"""


# ===========================================================
# BASE POLICY PACKAGE
# ===========================================================

BASE_POLICY = '''
package trustplane

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Default deny - everything is denied unless explicitly allowed
default allow := false

# Main decision entry point
allow if {
    some grant in grants
    grant == true
}

# Collect all deny reasons
deny_reasons contains reason if {
    some policy in input.policies
    policy.effect == "deny"
    matches_policy(policy, input.action, input.resource)
    reason := sprintf("Denied by policy: %s", [policy.name])
}

# Check if action/resource matches a policy
matches_policy(policy, action, resource) if {
    matches_action(policy.actions, action)
    matches_resource(policy.resources, resource)
    evaluate_conditions(policy.conditions, input.context)
}

# Action matching with wildcards
matches_action(patterns, action) if {
    some pattern in patterns
    glob_match(pattern, action)
}

# Resource matching with wildcards
matches_resource(patterns, resource) if {
    some pattern in patterns
    glob_match(pattern, resource)
}

# Glob pattern matching (supports * wildcard)
glob_match(pattern, value) if {
    pattern == "*"
}

glob_match(pattern, value) if {
    pattern == value
}

glob_match(pattern, value) if {
    contains(pattern, "*")
    parts := split(pattern, "*")
    startswith(value, parts[0])
    endswith(value, parts[count(parts)-1])
}

# Condition evaluation
evaluate_conditions(conditions, context) if {
    count(conditions) == 0
}

evaluate_conditions(conditions, context) if {
    count(conditions) > 0
    every key, expected in conditions {
        evaluate_condition(key, expected, context)
    }
}

evaluate_condition(key, expected, context) if {
    is_object(expected)
    op := expected.operator
    value := expected.value
    actual := context[key]
    apply_operator(op, actual, value)
}

evaluate_condition(key, expected, context) if {
    not is_object(expected)
    context[key] == expected
}

# Operators for condition evaluation
apply_operator("eq", actual, value) if { actual == value }
apply_operator("ne", actual, value) if { actual != value }
apply_operator("gt", actual, value) if { actual > value }
apply_operator("gte", actual, value) if { actual >= value }
apply_operator("lt", actual, value) if { actual < value }
apply_operator("lte", actual, value) if { actual <= value }
apply_operator("in", actual, value) if { actual in value }
apply_operator("not_in", actual, value) if { not actual in value }
apply_operator("contains", actual, value) if { contains(actual, value) }
apply_operator("startswith", actual, value) if { startswith(actual, value) }
apply_operator("endswith", actual, value) if { endswith(actual, value) }
'''


# ===========================================================
# RBAC POLICY PACKAGE
# ===========================================================

RBAC_POLICY = '''
package trustplane.rbac

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Role hierarchy (higher roles inherit lower role permissions)
role_hierarchy := {
    "admin": ["manager", "user", "viewer"],
    "manager": ["user", "viewer"],
    "user": ["viewer"],
    "viewer": [],
}

# Get all effective roles (including inherited)
effective_roles[role] if {
    role := input.user.role
}

effective_roles[inherited] if {
    base := input.user.role
    inherited := role_hierarchy[base][_]
}

# Role-based grants
grants contains true if {
    some policy in input.policies
    policy.effect == "allow"
    policy.type == "rbac"
    policy.role in effective_roles
    data.trustplane.matches_policy(policy, input.action, input.resource)
}

# Role-specific permissions
role_permissions := {
    "admin": [
        "workflow:*",
        "sla:*",
        "policy:*",
        "org:*",
        "user:*",
        "audit:*",
        "agent:*",
    ],
    "manager": [
        "workflow:create",
        "workflow:read",
        "workflow:update",
        "workflow:transition",
        "sla:read",
        "sla:create",
        "user:read",
        "audit:read",
    ],
    "user": [
        "workflow:create",
        "workflow:read",
        "workflow:update",
        "workflow:transition",
        "sla:read",
    ],
    "viewer": [
        "workflow:read",
        "sla:read",
        "audit:read",
    ],
}

# Check if role has permission for action
role_has_permission(role, action) if {
    perms := role_permissions[role]
    some perm in perms
    data.trustplane.glob_match(perm, action)
}

# Role-based allow
allow if {
    some role in effective_roles
    role_has_permission(role, input.action)
}
'''


# ===========================================================
# ABAC POLICY PACKAGE
# ===========================================================

ABAC_POLICY = '''
package trustplane.abac

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Attribute-based grants
grants contains true if {
    some policy in input.policies
    policy.effect == "allow"
    policy.type == "abac"
    data.trustplane.matches_policy(policy, input.action, input.resource)
}

# Time-based access control
allow if {
    input.context.time_of_day >= 9
    input.context.time_of_day < 17
    input.context.is_business_day == true
    input.action == "workflow:create"
}

# Resource owner can always access their resources
allow if {
    input.resource_owner == input.user.id
    startswith(input.action, "workflow:")
    not endswith(input.action, ":delete")
}

# Department-based access
allow if {
    input.user.department == input.resource_department
    input.action in ["workflow:read", "workflow:update"]
}

# Sensitivity level access
allow if {
    sensitivity_levels := {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
    user_clearance := sensitivity_levels[input.user.clearance]
    resource_level := sensitivity_levels[input.resource_sensitivity]
    user_clearance >= resource_level
}
'''


# ===========================================================
# WORKFLOW POLICY PACKAGE
# ===========================================================

WORKFLOW_POLICY = '''
package trustplane.workflow

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Valid workflow state transitions
valid_transitions := {
    "pending": ["active", "cancelled"],
    "active": ["paused", "completed", "failed", "cancelled"],
    "paused": ["active", "cancelled", "failed"],
    "completed": [],
    "failed": [],
    "cancelled": [],
}

# Check if transition is valid
transition_allowed if {
    from_state := input.workflow.current_state
    to_state := input.requested_state
    allowed := valid_transitions[from_state]
    to_state in allowed
}

# Transitions requiring reason
requires_reason if {
    from_state := input.workflow.current_state
    to_state := input.requested_state
    
    # These transitions require a reason
    reason_required := [
        ["active", "failed"],
        ["active", "cancelled"],
        ["paused", "cancelled"],
        ["paused", "failed"],
        ["pending", "cancelled"],
    ]
    
    [from_state, to_state] in reason_required
}

# Transition denied reasons
deny_transition_reasons contains reason if {
    not transition_allowed
    reason := sprintf("Invalid transition from %s to %s", [
        input.workflow.current_state,
        input.requested_state
    ])
}

deny_transition_reasons contains reason if {
    requires_reason
    not input.reason
    reason := "Reason required for this transition"
}

deny_transition_reasons contains reason if {
    requires_reason
    input.reason
    count(input.reason) < 10
    reason := "Reason must be at least 10 characters"
}

# Only assigned user or admin can transition
deny_transition_reasons contains reason if {
    input.workflow.assignee_id != null
    input.workflow.assignee_id != input.user.id
    input.user.role != "admin"
    reason := "Only assigned user or admin can transition this workflow"
}

# Final decision
allow_transition if {
    transition_allowed
    count(deny_transition_reasons) == 0
}
'''


# ===========================================================
# SLA POLICY PACKAGE
# ===========================================================

SLA_POLICY = '''
package trustplane.sla

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# SLA priority escalation rules
escalation_required if {
    input.sla.status == "soft_breach"
    input.sla.priority in ["p1", "p2"]
}

escalation_required if {
    input.sla.status == "hard_breach"
}

# Determine escalation level
escalation_level := "critical" if {
    input.sla.status == "hard_breach"
    input.sla.priority == "p1"
}

escalation_level := "high" if {
    input.sla.status == "hard_breach"
    input.sla.priority == "p2"
}

escalation_level := "medium" if {
    input.sla.status == "soft_breach"
    input.sla.priority in ["p1", "p2"]
}

escalation_level := "low" if {
    input.sla.status == "soft_breach"
    input.sla.priority in ["p3", "p4"]
}

escalation_level := "none" if {
    input.sla.status in ["active", "pending", "met"]
}

# Recommended actions based on SLA status
recommended_actions contains action if {
    escalation_level == "critical"
    action := "Immediate manager notification required"
}

recommended_actions contains action if {
    escalation_level in ["critical", "high"]
    action := "Reassign to available senior staff"
}

recommended_actions contains action if {
    input.sla.elapsed_minutes > input.sla.soft_limit * 0.75
    input.sla.status == "active"
    action := "Warning: Approaching soft breach threshold"
}

recommended_actions contains action if {
    input.sla.elapsed_minutes > input.sla.hard_limit * 0.9
    input.sla.status in ["active", "soft_breach"]
    action := "Critical: Approaching hard breach threshold"
}

# Can SLA be paused?
can_pause if {
    input.sla.status == "active"
    input.pause_reason in ["waiting_customer", "blocked_external", "approved_hold"]
}

deny_pause_reasons contains reason if {
    input.sla.status != "active"
    reason := sprintf("Cannot pause SLA in status: %s", [input.sla.status])
}

deny_pause_reasons contains reason if {
    input.sla.status == "active"
    not input.pause_reason
    reason := "Pause reason is required"
}

deny_pause_reasons contains reason if {
    input.sla.status == "active"
    input.pause_reason
    valid_reasons := ["waiting_customer", "blocked_external", "approved_hold"]
    not input.pause_reason in valid_reasons
    reason := sprintf("Invalid pause reason. Must be one of: %v", [valid_reasons])
}
'''


# ===========================================================
# AGENT POLICY PACKAGE
# ===========================================================

AGENT_POLICY = '''
package trustplane.agent

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Agent decision boundaries
# Agents can ONLY make decisions, never directly mutate data

# Actions agents are allowed to recommend
allowed_agent_actions := [
    "recommend_transition",
    "recommend_assignment",
    "recommend_escalation",
    "recommend_priority_change",
    "predict_breach",
    "analyze_workflow",
    "generate_summary",
]

# Actions agents are NEVER allowed to perform directly
forbidden_agent_actions := [
    "workflow:create",
    "workflow:delete",
    "workflow:transition",
    "sla:create",
    "sla:delete",
    "policy:create",
    "policy:delete",
    "user:create",
    "user:delete",
]

# Agent action is allowed
agent_action_allowed if {
    input.agent.action in allowed_agent_actions
}

# Agent action is forbidden
agent_action_forbidden if {
    input.agent.action in forbidden_agent_actions
}

deny_agent_reasons contains reason if {
    agent_action_forbidden
    reason := sprintf("Agent cannot directly perform action: %s", [input.agent.action])
}

# Agent confidence threshold
confidence_threshold := 0.8

deny_agent_reasons contains reason if {
    input.agent.confidence < confidence_threshold
    reason := sprintf("Agent confidence %v below threshold %v", [
        input.agent.confidence,
        confidence_threshold
    ])
}

# Agent must provide reasoning
deny_agent_reasons contains reason if {
    not input.agent.reasoning
    reason := "Agent must provide reasoning for recommendation"
}

deny_agent_reasons contains reason if {
    input.agent.reasoning
    count(input.agent.reasoning) < 20
    reason := "Agent reasoning must be at least 20 characters"
}

# Final agent decision allowed
agent_decision_allowed if {
    agent_action_allowed
    count(deny_agent_reasons) == 0
}

# Human approval required for certain decisions
requires_human_approval if {
    input.agent.action == "recommend_transition"
    input.workflow.current_state in ["active", "paused"]
}

requires_human_approval if {
    input.agent.action == "recommend_priority_change"
    input.priority_change.from_priority in ["p1", "p2"]
}

requires_human_approval if {
    input.agent.confidence < 0.95
}
'''


# ===========================================================
# AUDIT POLICY PACKAGE
# ===========================================================

AUDIT_POLICY = '''
package trustplane.audit

import future.keywords.if
import future.keywords.in
import future.keywords.contains

# Actions that must be audited
must_audit if {
    # All write operations
    input.action_type in ["create", "update", "delete", "transition"]
}

must_audit if {
    # All policy evaluations
    startswith(input.action, "policy:")
}

must_audit if {
    # All SLA breaches
    input.event_type in ["sla.soft_breach", "sla.hard_breach"]
}

must_audit if {
    # All agent decisions
    startswith(input.action, "agent:")
}

must_audit if {
    # All authentication events
    input.event_type in ["auth.login", "auth.logout", "auth.failed"]
}

# Audit retention rules
retention_days := 90 if {
    input.audit_type == "standard"
}

retention_days := 365 if {
    input.audit_type == "compliance"
}

retention_days := 2555 if {  # 7 years
    input.audit_type == "financial"
}

# Sensitive data that must be masked in audit logs
sensitive_fields := [
    "password",
    "api_key",
    "secret",
    "token",
    "ssn",
    "credit_card",
]

should_mask_field(field) if {
    some sensitive in sensitive_fields
    contains(lower(field), sensitive)
}
'''


# ===========================================================
# DEFAULT POLICIES (JSON format for database storage)
# ===========================================================

DEFAULT_POLICIES = [
    {
        "name": "admin_full_access",
        "description": "Administrators have full access to all resources",
        "effect": "allow",
        "type": "rbac",
        "role": "admin",
        "actions": ["*"],
        "resources": ["*"],
        "conditions": {},
        "priority": 1,
        "is_system": True,
    },
    {
        "name": "manager_workflow_access",
        "description": "Managers can manage workflows and view SLAs",
        "effect": "allow",
        "type": "rbac",
        "role": "manager",
        "actions": ["workflow:*", "sla:read", "user:read"],
        "resources": ["*"],
        "conditions": {},
        "priority": 10,
        "is_system": True,
    },
    {
        "name": "user_own_workflow_access",
        "description": "Users can manage their own workflows",
        "effect": "allow",
        "type": "abac",
        "actions": ["workflow:read", "workflow:update", "workflow:transition"],
        "resources": ["workflow:*"],
        "conditions": {
            "resource_owner": {"operator": "eq", "value": "${user.id}"}
        },
        "priority": 20,
        "is_system": True,
    },
    {
        "name": "viewer_read_only",
        "description": "Viewers can only read workflows and SLAs",
        "effect": "allow",
        "type": "rbac",
        "role": "viewer",
        "actions": ["workflow:read", "sla:read"],
        "resources": ["*"],
        "conditions": {},
        "priority": 30,
        "is_system": True,
    },
    {
        "name": "deny_delete_active_sla",
        "description": "Cannot delete SLAs with active instances",
        "effect": "deny",
        "type": "abac",
        "actions": ["sla:delete"],
        "resources": ["sla:definition:*"],
        "conditions": {
            "sla_has_active_instances": {"operator": "eq", "value": True}
        },
        "priority": 1,
        "is_system": True,
    },
    {
        "name": "business_hours_workflow_create",
        "description": "Workflow creation only during business hours for non-admins",
        "effect": "deny",
        "type": "abac",
        "actions": ["workflow:create"],
        "resources": ["workflow:*"],
        "conditions": {
            "is_business_hours": {"operator": "eq", "value": False},
            "user_role": {"operator": "ne", "value": "admin"}
        },
        "priority": 5,
        "is_system": False,
    },
]


# All Rego policies bundled together
ALL_REGO_POLICIES = {
    "base": BASE_POLICY,
    "rbac": RBAC_POLICY,
    "abac": ABAC_POLICY,
    "workflow": WORKFLOW_POLICY,
    "sla": SLA_POLICY,
    "agent": AGENT_POLICY,
    "audit": AUDIT_POLICY,
}
