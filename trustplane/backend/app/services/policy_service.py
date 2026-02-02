"""
Policy Service (Event-Sourced)

This module provides the service layer for policy management with full
event sourcing integration. Every policy change is recorded in the
event ledger for complete auditability.

Architecture:
=============
1. PolicyService: Main service class for policy CRUD
2. Event integration: All changes emit events to the dispatcher
3. Cache management: Policies cached for fast evaluation
4. Tenant isolation: Policies scoped to organization
"""

from typing import Any
from datetime import datetime, timezone
from uuid import UUID, uuid4
import json
import hashlib

from app.core.database import get_db_connection
from app.engines.policy_engine import (
    PolicyEngine,
    PolicyInput,
    PolicyResult,
    PolicyEffect,
    Policy,
    get_policy_engine,
)
from app.engines.rego_policies import DEFAULT_POLICIES
from app.services.event_dispatcher import get_event_dispatcher


class PolicyService:
    """
    Event-sourced Policy Service.
    
    All policy operations are:
    1. Validated against business rules
    2. Persisted to the database
    3. Recorded as events in the ledger
    4. Dispatched through the event system
    
    Thread Safety:
    =============
    The service uses the singleton PolicyEngine.
    Policy cache is refreshed on any mutation.
    """
    
    def __init__(self, org_id: UUID | str):
        self.org_id = UUID(org_id) if isinstance(org_id, str) else org_id
        self.engine = get_policy_engine()
        self.dispatcher = get_event_dispatcher()
        self._policies_loaded = False
    
    async def initialize(self) -> None:
        """Initialize the service and load policies."""
        await self._load_policies()
        
        # Seed default policies if none exist
        if not self.engine.policies:
            await self._seed_default_policies()
    
    async def _load_policies(self) -> None:
        """Load policies from database."""
        async with get_db_connection() as conn:
            rows = await conn.fetch("""
                SELECT 
                    id, name, description, effect, type, role,
                    actions, resources, conditions, priority,
                    is_active, is_system, created_at, updated_at
                FROM policies
                WHERE org_id = $1 AND is_active = true
                ORDER BY priority ASC
            """, self.org_id)
            
            policies = []
            for row in rows:
                policies.append({
                    "id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"] or "",
                    "effect": row["effect"],
                    "type": row["type"] or "abac",
                    "role": row["role"],
                    "actions": row["actions"] or [],
                    "resources": row["resources"] or ["*"],
                    "conditions": row["conditions"] or {},
                    "priority": row["priority"],
                    "is_system": row["is_system"],
                })
            
            self.engine.load_policies(policies)
            self._policies_loaded = True
    
    async def _seed_default_policies(self) -> None:
        """Seed default system policies."""
        for policy_data in DEFAULT_POLICIES:
            await self.create_policy(
                name=policy_data["name"],
                description=policy_data["description"],
                effect=policy_data["effect"],
                actions=policy_data["actions"],
                resources=policy_data.get("resources", ["*"]),
                conditions=policy_data.get("conditions", {}),
                priority=policy_data["priority"],
                policy_type=policy_data.get("type", "abac"),
                role=policy_data.get("role"),
                is_system=policy_data.get("is_system", False),
                user_id=None,  # System seeded
            )
    
    # =====================================================
    # Policy CRUD Operations
    # =====================================================
    
    async def create_policy(
        self,
        name: str,
        description: str,
        effect: str,
        actions: list[str],
        resources: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
        priority: int = 100,
        policy_type: str = "abac",
        role: str | None = None,
        is_system: bool = False,
        user_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new policy.
        
        Emits: policy.created event
        """
        policy_id = uuid4()
        now = datetime.now(timezone.utc)
        resources = resources or ["*"]
        conditions = conditions or {}
        
        # Validate effect
        if effect not in ["allow", "deny"]:
            raise ValueError(f"Invalid effect: {effect}. Must be 'allow' or 'deny'")
        
        # Validate RBAC policy has role
        if policy_type == "rbac" and not role:
            raise ValueError("RBAC policies must specify a role")
        
        # Validate actions
        if not actions:
            raise ValueError("Policy must have at least one action")
        
        async with get_db_connection() as conn:
            # Check for duplicate name
            existing = await conn.fetchrow("""
                SELECT id FROM policies
                WHERE org_id = $1 AND name = $2 AND is_active = true
            """, self.org_id, name)
            
            if existing:
                raise ValueError(f"Policy with name '{name}' already exists")
            
            # Insert policy
            await conn.execute("""
                INSERT INTO policies (
                    id, org_id, name, description, effect, type, role,
                    actions, resources, conditions, priority,
                    is_active, is_system, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    true, $12, $13, $13
                )
            """,
                policy_id, self.org_id, name, description, effect,
                policy_type, role, actions, resources,
                json.dumps(conditions), priority, is_system, now
            )
            
            # Record event
            await self._emit_event(
                event_type="policy.created",
                aggregate_id=policy_id,
                user_id=user_id,
                payload={
                    "policy_id": str(policy_id),
                    "name": name,
                    "effect": effect,
                    "type": policy_type,
                    "role": role,
                    "actions": actions,
                    "resources": resources,
                    "priority": priority,
                    "is_system": is_system,
                },
            )
        
        # Reload policies
        await self._load_policies()
        
        return {
            "id": str(policy_id),
            "name": name,
            "description": description,
            "effect": effect,
            "type": policy_type,
            "role": role,
            "actions": actions,
            "resources": resources,
            "conditions": conditions,
            "priority": priority,
            "is_system": is_system,
            "created_at": now.isoformat(),
        }
    
    async def get_policy(self, policy_id: UUID | str) -> dict[str, Any] | None:
        """Get a policy by ID."""
        policy_id = UUID(policy_id) if isinstance(policy_id, str) else policy_id
        
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    id, name, description, effect, type, role,
                    actions, resources, conditions, priority,
                    is_active, is_system, created_at, updated_at
                FROM policies
                WHERE id = $1 AND org_id = $2
            """, policy_id, self.org_id)
            
            if not row:
                return None
            
            return {
                "id": str(row["id"]),
                "name": row["name"],
                "description": row["description"],
                "effect": row["effect"],
                "type": row["type"],
                "role": row["role"],
                "actions": row["actions"],
                "resources": row["resources"],
                "conditions": row["conditions"],
                "priority": row["priority"],
                "is_active": row["is_active"],
                "is_system": row["is_system"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
            }
    
    async def list_policies(
        self,
        include_inactive: bool = False,
        policy_type: str | None = None,
        effect: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all policies with optional filters."""
        async with get_db_connection() as conn:
            query = """
                SELECT 
                    id, name, description, effect, type, role,
                    actions, resources, conditions, priority,
                    is_active, is_system, created_at, updated_at
                FROM policies
                WHERE org_id = $1
            """
            params = [self.org_id]
            
            if not include_inactive:
                query += " AND is_active = true"
            
            if policy_type:
                query += f" AND type = ${len(params) + 1}"
                params.append(policy_type)
            
            if effect:
                query += f" AND effect = ${len(params) + 1}"
                params.append(effect)
            
            query += " ORDER BY priority ASC, name ASC"
            
            rows = await conn.fetch(query, *params)
            
            return [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"],
                    "effect": row["effect"],
                    "type": row["type"],
                    "role": row["role"],
                    "actions": row["actions"],
                    "resources": row["resources"],
                    "conditions": row["conditions"],
                    "priority": row["priority"],
                    "is_active": row["is_active"],
                    "is_system": row["is_system"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in rows
            ]
    
    async def update_policy(
        self,
        policy_id: UUID | str,
        user_id: UUID | str,
        **updates,
    ) -> dict[str, Any]:
        """
        Update a policy.
        
        Emits: policy.updated event
        """
        policy_id = UUID(policy_id) if isinstance(policy_id, str) else policy_id
        user_id = UUID(user_id) if isinstance(user_id, str) else user_id
        
        # Get existing policy
        existing = await self.get_policy(policy_id)
        if not existing:
            raise ValueError(f"Policy {policy_id} not found")
        
        # System policies cannot be updated
        if existing["is_system"]:
            raise ValueError("System policies cannot be modified")
        
        now = datetime.now(timezone.utc)
        
        # Build update fields
        allowed_fields = [
            "name", "description", "effect", "actions", "resources",
            "conditions", "priority", "role", "type"
        ]
        
        update_fields = []
        update_values = []
        changes = {}
        
        for field in allowed_fields:
            if field in updates:
                update_fields.append(f"{field} = ${len(update_values) + 3}")
                value = updates[field]
                if field == "conditions":
                    value = json.dumps(value)
                update_values.append(value)
                changes[field] = {
                    "old": existing.get(field),
                    "new": updates[field],
                }
        
        if not update_fields:
            return existing
        
        update_fields.append(f"updated_at = ${len(update_values) + 3}")
        update_values.append(now)
        
        async with get_db_connection() as conn:
            await conn.execute(f"""
                UPDATE policies
                SET {", ".join(update_fields)}
                WHERE id = $1 AND org_id = $2
            """, policy_id, self.org_id, *update_values)
            
            # Record event
            await self._emit_event(
                event_type="policy.updated",
                aggregate_id=policy_id,
                user_id=user_id,
                payload={
                    "policy_id": str(policy_id),
                    "changes": changes,
                },
            )
        
        # Reload policies
        await self._load_policies()
        
        return await self.get_policy(policy_id)
    
    async def delete_policy(
        self,
        policy_id: UUID | str,
        user_id: UUID | str,
    ) -> bool:
        """
        Soft-delete a policy.
        
        Emits: policy.deleted event
        """
        policy_id = UUID(policy_id) if isinstance(policy_id, str) else policy_id
        user_id = UUID(user_id) if isinstance(user_id, str) else user_id
        
        # Get existing policy
        existing = await self.get_policy(policy_id)
        if not existing:
            return False
        
        # System policies cannot be deleted
        if existing["is_system"]:
            raise ValueError("System policies cannot be deleted")
        
        now = datetime.now(timezone.utc)
        
        async with get_db_connection() as conn:
            await conn.execute("""
                UPDATE policies
                SET is_active = false, updated_at = $3
                WHERE id = $1 AND org_id = $2
            """, policy_id, self.org_id, now)
            
            # Record event
            await self._emit_event(
                event_type="policy.deleted",
                aggregate_id=policy_id,
                user_id=user_id,
                payload={
                    "policy_id": str(policy_id),
                    "name": existing["name"],
                },
            )
        
        # Reload policies
        await self._load_policies()
        
        return True
    
    # =====================================================
    # Policy Evaluation
    # =====================================================
    
    async def evaluate(
        self,
        user_id: str,
        user_role: str,
        action: str,
        resource: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyResult:
        """
        Evaluate policies for a request.
        
        Emits: policy.evaluated event (for audit)
        """
        if not self._policies_loaded:
            await self._load_policies()
        
        context = context or {}
        
        input_data = PolicyInput(
            user={"id": user_id, "role": user_role},
            action=action,
            resource=resource,
            context=context,
        )
        
        result = self.engine.evaluate(input_data)
        
        # Record evaluation in audit log
        await self._emit_event(
            event_type="policy.evaluated",
            aggregate_id=uuid4(),  # New ID for each evaluation
            user_id=UUID(user_id) if user_id else None,
            payload={
                "action": action,
                "resource": resource,
                "decision": result.decision.value,
                "allowed": result.allowed,
                "matched_policies": result.matched_policies,
                "evaluation_time_ms": result.evaluation_time_ms,
                "input_hash": result.input_hash,
            },
        )
        
        return result
    
    async def evaluate_workflow_transition(
        self,
        user_id: str,
        user_role: str,
        workflow_id: str,
        current_state: str,
        to_state: str,
        reason: str | None = None,
        workflow_owner_id: str | None = None,
    ) -> PolicyResult:
        """Evaluate workflow transition policy."""
        if not self._policies_loaded:
            await self._load_policies()
        
        user = {"id": user_id, "role": user_role}
        workflow = {
            "id": workflow_id,
            "current_state": current_state,
            "assignee_id": workflow_owner_id,
        }
        
        result = self.engine.evaluate_workflow_transition(
            user=user,
            workflow=workflow,
            to_state=to_state,
            reason=reason,
        )
        
        # Record evaluation
        await self._emit_event(
            event_type="policy.workflow_transition_evaluated",
            aggregate_id=UUID(workflow_id),
            user_id=UUID(user_id) if user_id else None,
            payload={
                "workflow_id": workflow_id,
                "from_state": current_state,
                "to_state": to_state,
                "decision": result.decision.value,
                "allowed": result.allowed,
                "reasons": result.reasons,
            },
        )
        
        return result
    
    async def evaluate_agent_decision(
        self,
        agent_id: str,
        action: str,
        confidence: float,
        reasoning: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyResult:
        """Evaluate AI agent decision policy."""
        if not self._policies_loaded:
            await self._load_policies()
        
        agent = {
            "id": agent_id,
            "action": action,
            "confidence": confidence,
            "reasoning": reasoning,
        }
        
        result = self.engine.evaluate_agent_decision(
            agent=agent,
            action=action,
            context=context,
        )
        
        # Record evaluation
        await self._emit_event(
            event_type="policy.agent_decision_evaluated",
            aggregate_id=uuid4(),
            user_id=None,  # System/agent action
            payload={
                "agent_id": agent_id,
                "action": action,
                "confidence": confidence,
                "decision": result.decision.value,
                "allowed": result.allowed,
                "requires_human_approval": result.requires_human_approval,
            },
        )
        
        return result
    
    async def get_effective_permissions(
        self,
        user_id: str,
        user_role: str,
    ) -> list[str]:
        """Get all effective permissions for a user."""
        if not self._policies_loaded:
            await self._load_policies()
        
        return self.engine.get_effective_permissions(
            user_id=user_id,
            user_role=user_role,
        )
    
    # =====================================================
    # Role Management
    # =====================================================
    
    async def create_role(
        self,
        name: str,
        description: str,
        permissions: list[str],
        user_id: UUID | str,
    ) -> dict[str, Any]:
        """
        Create a custom role with RBAC policy.
        
        Emits: role.created event
        """
        role_id = uuid4()
        now = datetime.now(timezone.utc)
        
        async with get_db_connection() as conn:
            # Check for duplicate
            existing = await conn.fetchrow("""
                SELECT id FROM roles
                WHERE org_id = $1 AND name = $2 AND is_active = true
            """, self.org_id, name)
            
            if existing:
                raise ValueError(f"Role '{name}' already exists")
            
            await conn.execute("""
                INSERT INTO roles (
                    id, org_id, name, description, permissions,
                    is_active, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, true, $6, $6)
            """, role_id, self.org_id, name, description, permissions, now)
            
            # Create RBAC policy for this role
            await self.create_policy(
                name=f"role_{name}_policy",
                description=f"Auto-generated policy for role: {name}",
                effect="allow",
                actions=permissions,
                resources=["*"],
                policy_type="rbac",
                role=name,
                user_id=user_id,
            )
            
            await self._emit_event(
                event_type="role.created",
                aggregate_id=role_id,
                user_id=user_id,
                payload={
                    "role_id": str(role_id),
                    "name": name,
                    "permissions": permissions,
                },
            )
        
        return {
            "id": str(role_id),
            "name": name,
            "description": description,
            "permissions": permissions,
            "created_at": now.isoformat(),
        }
    
    async def list_roles(self) -> list[dict[str, Any]]:
        """List all roles for the organization."""
        async with get_db_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, name, description, permissions, created_at, updated_at
                FROM roles
                WHERE org_id = $1 AND is_active = true
                ORDER BY name ASC
            """, self.org_id)
            
            return [
                {
                    "id": str(row["id"]),
                    "name": row["name"],
                    "description": row["description"],
                    "permissions": row["permissions"],
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
                for row in rows
            ]
    
    # =====================================================
    # Event Emission
    # =====================================================
    
    async def _emit_event(
        self,
        event_type: str,
        aggregate_id: UUID,
        user_id: UUID | str | None,
        payload: dict[str, Any],
    ) -> None:
        """Emit event through the dispatcher."""
        if user_id and isinstance(user_id, str):
            user_id = UUID(user_id)
        
        event = {
            "id": str(uuid4()),
            "type": event_type,
            "aggregate_id": str(aggregate_id),
            "aggregate_type": "policy",
            "org_id": str(self.org_id),
            "user_id": str(user_id) if user_id else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        
        await self.dispatcher.dispatch(event)


# Factory function
async def get_policy_service(org_id: UUID | str) -> PolicyService:
    """Get an initialized policy service for an organization."""
    service = PolicyService(org_id)
    await service.initialize()
    return service
