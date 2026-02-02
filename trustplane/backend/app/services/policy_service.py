"""
Policy Service - RBAC + ABAC enforcement
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from dataclasses import dataclass

from app.models.policy import Policy, PolicyCreate, PolicyEffect, Role


@dataclass
class PolicyDecision:
    """Result of policy evaluation"""
    allowed: bool
    reasons: List[str]
    matched_policies: List[UUID]
    evaluation_time_ms: float


class PolicyService:
    """
    Policy enforcement engine with RBAC + ABAC support.
    """
    
    async def evaluate(
        self,
        org_id: UUID,
        actor_id: UUID,
        action: str,
        resource: str,
        context: Dict[str, Any] = None
    ) -> PolicyDecision:
        """
        Evaluate policies for an action.
        
        Evaluation order:
        1. Explicit DENY policies (highest priority)
        2. ALLOW policies by priority
        3. Default DENY if no match
        """
        raise NotImplementedError("Will be implemented in Step 9")
    
    async def create_policy(
        self,
        org_id: UUID,
        policy: PolicyCreate,
        actor_id: UUID
    ) -> Policy:
        """Create a new policy"""
        raise NotImplementedError("Will be implemented in Step 9")
    
    async def get_user_permissions(
        self,
        org_id: UUID,
        user_id: UUID
    ) -> List[str]:
        """Get all effective permissions for a user"""
        raise NotImplementedError("Will be implemented in Step 9")
    
    async def check_permission(
        self,
        org_id: UUID,
        user_id: UUID,
        permission: str
    ) -> bool:
        """Quick check if user has a specific permission"""
        raise NotImplementedError("Will be implemented in Step 9")
    
    async def assign_role(
        self,
        org_id: UUID,
        user_id: UUID,
        role_id: UUID,
        actor_id: UUID
    ) -> None:
        """Assign a role to a user"""
        raise NotImplementedError("Will be implemented in Step 9")


# Singleton instance
policy_service = PolicyService()
