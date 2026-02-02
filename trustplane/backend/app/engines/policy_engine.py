"""
Policy Engine - RBAC + ABAC evaluation logic
"""
from typing import Dict, Any, List, Optional
from uuid import UUID
from dataclasses import dataclass
import re


@dataclass
class PolicyMatch:
    """Policy match result"""
    policy_id: UUID
    effect: str
    priority: int
    conditions_met: bool


class PolicyEngine:
    """
    Core policy evaluation engine.
    Supports RBAC (role-based) and ABAC (attribute-based) policies.
    """
    
    def evaluate_policies(
        self,
        policies: List[Dict[str, Any]],
        action: str,
        resource: str,
        context: Dict[str, Any]
    ) -> tuple[bool, List[str], List[UUID]]:
        """
        Evaluate all policies and return decision.
        
        Evaluation order:
        1. Sort by priority (lower = higher priority)
        2. Check DENY policies first
        3. Check ALLOW policies
        4. Default DENY if no match
        """
        # Sort by priority
        sorted_policies = sorted(policies, key=lambda p: p.get("priority", 100))
        
        matched = []
        reasons = []
        
        # First pass: check for explicit DENY
        for policy in sorted_policies:
            if policy["effect"] == "deny":
                if self._matches_policy(policy, action, resource, context):
                    matched.append(UUID(policy["id"]))
                    reasons.append(f"Denied by policy: {policy['name']}")
                    return False, reasons, matched
        
        # Second pass: check for ALLOW
        for policy in sorted_policies:
            if policy["effect"] == "allow":
                if self._matches_policy(policy, action, resource, context):
                    matched.append(UUID(policy["id"]))
                    reasons.append(f"Allowed by policy: {policy['name']}")
                    return True, reasons, matched
        
        # Default deny
        reasons.append("No matching policy found - default deny")
        return False, reasons, matched
    
    def _matches_policy(
        self,
        policy: Dict[str, Any],
        action: str,
        resource: str,
        context: Dict[str, Any]
    ) -> bool:
        """Check if action/resource matches policy"""
        # Check action match
        if not self._matches_pattern(action, policy.get("actions", [])):
            return False
        
        # Check resource match
        if not self._matches_pattern(resource, policy.get("resources", [])):
            return False
        
        # Check conditions
        conditions = policy.get("conditions", {})
        if conditions and not self._evaluate_conditions(conditions, context):
            return False
        
        return True
    
    def _matches_pattern(self, value: str, patterns: List[str]) -> bool:
        """Check if value matches any pattern (supports wildcards)"""
        for pattern in patterns:
            # Convert wildcard pattern to regex
            regex = pattern.replace("*", ".*").replace("?", ".")
            if re.fullmatch(regex, value):
                return True
        return False
    
    def _evaluate_conditions(
        self,
        conditions: Dict[str, Any],
        context: Dict[str, Any]
    ) -> bool:
        """Evaluate ABAC conditions"""
        for key, expected in conditions.items():
            actual = context.get(key)
            
            if isinstance(expected, dict):
                # Complex condition
                op = expected.get("operator", "eq")
                value = expected.get("value")
                
                if op == "eq" and actual != value:
                    return False
                elif op == "ne" and actual == value:
                    return False
                elif op == "in" and actual not in value:
                    return False
                elif op == "not_in" and actual in value:
                    return False
                elif op == "gt" and not (actual > value):
                    return False
                elif op == "gte" and not (actual >= value):
                    return False
                elif op == "lt" and not (actual < value):
                    return False
                elif op == "lte" and not (actual <= value):
                    return False
            else:
                # Simple equality
                if actual != expected:
                    return False
        
        return True
    
    def get_effective_permissions(
        self,
        policies: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract all allowed actions from policies"""
        permissions = set()
        
        for policy in policies:
            if policy["effect"] == "allow":
                for action in policy.get("actions", []):
                    if "*" not in action:
                        permissions.add(action)
        
        return list(permissions)


# Singleton instance
policy_engine = PolicyEngine()
