"""
Policy Management API Endpoints

This module provides REST API endpoints for policy management in TrustPlane.
All endpoints are authenticated and tenant-scoped.

Endpoints:
==========
- GET /policies - List all policies
- POST /policies - Create a new policy
- GET /policies/{id} - Get policy details
- PUT /policies/{id} - Update a policy
- DELETE /policies/{id} - Delete a policy
- POST /policies/evaluate - Evaluate policies for a request
- POST /policies/evaluate/workflow - Evaluate workflow transition
- POST /policies/evaluate/agent - Evaluate agent decision
- GET /policies/permissions - Get effective permissions
- GET /roles - List roles
- POST /roles - Create a role
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import Any
from uuid import UUID

from app.api.deps import get_current_user, get_org_id
from app.services.policy_service import get_policy_service, PolicyService
from app.engines.policy_engine import PolicyDecision


router = APIRouter()


# =====================================================
# Request/Response Models
# =====================================================

class PolicyCreate(BaseModel):
    """Request model for creating a policy."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    effect: str = Field(..., pattern="^(allow|deny)$")
    actions: list[str] = Field(..., min_items=1)
    resources: list[str] = Field(default=["*"])
    conditions: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=1, le=1000)
    type: str = Field(default="abac", pattern="^(rbac|abac|workflow|sla|agent)$")
    role: str | None = Field(default=None)


class PolicyUpdate(BaseModel):
    """Request model for updating a policy."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    effect: str | None = Field(default=None, pattern="^(allow|deny)$")
    actions: list[str] | None = Field(default=None, min_items=1)
    resources: list[str] | None = None
    conditions: dict[str, Any] | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)


class PolicyEvaluateRequest(BaseModel):
    """Request model for policy evaluation."""
    action: str = Field(..., min_length=1)
    resource: str = Field(..., min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class WorkflowTransitionRequest(BaseModel):
    """Request model for workflow transition evaluation."""
    workflow_id: str
    current_state: str
    to_state: str
    reason: str | None = None
    workflow_owner_id: str | None = None


class AgentDecisionRequest(BaseModel):
    """Request model for agent decision evaluation."""
    agent_id: str
    action: str
    confidence: float = Field(..., ge=0, le=1)
    reasoning: str = Field(..., min_length=20)
    context: dict[str, Any] = Field(default_factory=dict)


class RoleCreate(BaseModel):
    """Request model for creating a role."""
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default="", max_length=200)
    permissions: list[str] = Field(..., min_items=1)


class PolicyResponse(BaseModel):
    """Response model for policy data."""
    id: str
    name: str
    description: str
    effect: str
    type: str
    role: str | None
    actions: list[str]
    resources: list[str]
    conditions: dict[str, Any]
    priority: int
    is_active: bool
    is_system: bool
    created_at: str
    updated_at: str


class EvaluationResponse(BaseModel):
    """Response model for policy evaluation."""
    decision: str
    allowed: bool
    reasons: list[str]
    matched_policies: list[str]
    evaluation_time_ms: float
    input_hash: str
    timestamp: str
    escalation_level: str | None = None
    recommended_actions: list[str] = []
    requires_human_approval: bool = False


# =====================================================
# Dependency
# =====================================================

async def get_policy_svc(
    org_id: UUID = Depends(get_org_id),
) -> PolicyService:
    """Get policy service for current organization."""
    return await get_policy_service(org_id)


# =====================================================
# Policy Endpoints
# =====================================================

@router.get(
    "/",
    response_model=list[PolicyResponse],
    summary="List Policies",
    description="List all policies for the organization",
)
async def list_policies(
    include_inactive: bool = Query(False, description="Include inactive policies"),
    policy_type: str | None = Query(None, description="Filter by policy type"),
    effect: str | None = Query(None, description="Filter by effect (allow/deny)"),
    service: PolicyService = Depends(get_policy_svc),
) -> list[dict[str, Any]]:
    """List all policies with optional filters."""
    return await service.list_policies(
        include_inactive=include_inactive,
        policy_type=policy_type,
        effect=effect,
    )


@router.post(
    "/",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Policy",
    description="Create a new policy",
)
async def create_policy(
    request: PolicyCreate,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Create a new policy."""
    try:
        return await service.create_policy(
            name=request.name,
            description=request.description,
            effect=request.effect,
            actions=request.actions,
            resources=request.resources,
            conditions=request.conditions,
            priority=request.priority,
            policy_type=request.type,
            role=request.role,
            user_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/{policy_id}",
    response_model=PolicyResponse,
    summary="Get Policy",
    description="Get policy details by ID",
)
async def get_policy(
    policy_id: str,
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Get a policy by ID."""
    policy = await service.get_policy(policy_id)
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )
    return policy


@router.put(
    "/{policy_id}",
    response_model=PolicyResponse,
    summary="Update Policy",
    description="Update an existing policy",
)
async def update_policy(
    policy_id: str,
    request: PolicyUpdate,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Update a policy."""
    try:
        updates = request.model_dump(exclude_unset=True)
        return await service.update_policy(
            policy_id=policy_id,
            user_id=current_user["id"],
            **updates,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Policy",
    description="Delete (soft) a policy",
)
async def delete_policy(
    policy_id: str,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> None:
    """Delete a policy."""
    try:
        deleted = await service.delete_policy(
            policy_id=policy_id,
            user_id=current_user["id"],
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Policy {policy_id} not found",
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# =====================================================
# Policy Evaluation Endpoints
# =====================================================

@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate Policy",
    description="Evaluate policies for a request",
)
async def evaluate_policy(
    request: PolicyEvaluateRequest,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Evaluate policies for a given action and resource."""
    result = await service.evaluate(
        user_id=current_user["id"],
        user_role=current_user.get("role", "viewer"),
        action=request.action,
        resource=request.resource,
        context=request.context,
    )
    return result.to_dict()


@router.post(
    "/evaluate/workflow",
    response_model=EvaluationResponse,
    summary="Evaluate Workflow Transition",
    description="Evaluate if a workflow state transition is allowed",
)
async def evaluate_workflow_transition(
    request: WorkflowTransitionRequest,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Evaluate workflow transition policy."""
    result = await service.evaluate_workflow_transition(
        user_id=current_user["id"],
        user_role=current_user.get("role", "viewer"),
        workflow_id=request.workflow_id,
        current_state=request.current_state,
        to_state=request.to_state,
        reason=request.reason,
        workflow_owner_id=request.workflow_owner_id,
    )
    return result.to_dict()


@router.post(
    "/evaluate/agent",
    response_model=EvaluationResponse,
    summary="Evaluate Agent Decision",
    description="Evaluate if an AI agent decision is allowed",
)
async def evaluate_agent_decision(
    request: AgentDecisionRequest,
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Evaluate agent decision policy."""
    result = await service.evaluate_agent_decision(
        agent_id=request.agent_id,
        action=request.action,
        confidence=request.confidence,
        reasoning=request.reasoning,
        context=request.context,
    )
    return result.to_dict()


@router.get(
    "/permissions/effective",
    response_model=list[str],
    summary="Get Effective Permissions",
    description="Get all effective permissions for the current user",
)
async def get_effective_permissions(
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> list[str]:
    """Get effective permissions for the current user."""
    return await service.get_effective_permissions(
        user_id=current_user["id"],
        user_role=current_user.get("role", "viewer"),
    )


# =====================================================
# Role Endpoints
# =====================================================

@router.get(
    "/roles",
    summary="List Roles",
    description="List all roles for the organization",
)
async def list_roles(
    service: PolicyService = Depends(get_policy_svc),
) -> list[dict[str, Any]]:
    """List all roles."""
    return await service.list_roles()


@router.post(
    "/roles",
    status_code=status.HTTP_201_CREATED,
    summary="Create Role",
    description="Create a new role with associated permissions",
)
async def create_role(
    request: RoleCreate,
    current_user: dict = Depends(get_current_user),
    service: PolicyService = Depends(get_policy_svc),
) -> dict[str, Any]:
    """Create a new role."""
    try:
        return await service.create_role(
            name=request.name,
            description=request.description,
            permissions=request.permissions,
            user_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# =====================================================
# Rego Policy Info Endpoints
# =====================================================

@router.get(
    "/rego/packages",
    summary="List Rego Packages",
    description="List available Rego policy packages",
)
async def list_rego_packages() -> dict[str, Any]:
    """List available Rego policy packages."""
    from app.engines.rego_policies import ALL_REGO_POLICIES
    
    return {
        "packages": list(ALL_REGO_POLICIES.keys()),
        "description": {
            "base": "Base policy package with common functions",
            "rbac": "Role-Based Access Control policies",
            "abac": "Attribute-Based Access Control policies",
            "workflow": "Workflow state transition policies",
            "sla": "SLA enforcement policies",
            "agent": "AI Agent decision boundary policies",
            "audit": "Audit logging policies",
        },
    }


@router.get(
    "/rego/packages/{package_name}",
    summary="Get Rego Package",
    description="Get Rego policy source for a package",
)
async def get_rego_package(package_name: str) -> dict[str, Any]:
    """Get Rego policy source for a package."""
    from app.engines.rego_policies import ALL_REGO_POLICIES
    
    if package_name not in ALL_REGO_POLICIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Package '{package_name}' not found",
        )
    
    return {
        "package": package_name,
        "source": ALL_REGO_POLICIES[package_name],
    }


@router.get(
    "/operators",
    summary="List Operators",
    description="List available condition operators",
)
async def list_operators() -> dict[str, Any]:
    """List available condition operators."""
    return {
        "operators": [
            {"name": "eq", "description": "Equal to", "example": '{"operator": "eq", "value": "admin"}'},
            {"name": "ne", "description": "Not equal to", "example": '{"operator": "ne", "value": "guest"}'},
            {"name": "gt", "description": "Greater than", "example": '{"operator": "gt", "value": 10}'},
            {"name": "gte", "description": "Greater than or equal", "example": '{"operator": "gte", "value": 18}'},
            {"name": "lt", "description": "Less than", "example": '{"operator": "lt", "value": 100}'},
            {"name": "lte", "description": "Less than or equal", "example": '{"operator": "lte", "value": 50}'},
            {"name": "in", "description": "In list", "example": '{"operator": "in", "value": ["admin", "manager"]}'},
            {"name": "not_in", "description": "Not in list", "example": '{"operator": "not_in", "value": ["guest"]}'},
            {"name": "contains", "description": "Contains substring", "example": '{"operator": "contains", "value": "admin"}'},
            {"name": "startswith", "description": "Starts with", "example": '{"operator": "startswith", "value": "user:"}'},
            {"name": "endswith", "description": "Ends with", "example": '{"operator": "endswith", "value": ":read"}'},
            {"name": "matches", "description": "Regex match", "example": '{"operator": "matches", "value": "^[a-z]+$"}'},
            {"name": "exists", "description": "Field exists", "example": '{"operator": "exists", "value": true}'},
            {"name": "not_exists", "description": "Field does not exist", "example": '{"operator": "not_exists", "value": true}'},
        ],
        "variable_references": {
            "description": "Use ${path.to.value} to reference dynamic values",
            "examples": [
                '{"operator": "eq", "value": "${user.id}"}',
                '{"operator": "in", "value": "${context.allowed_departments}"}',
            ],
        },
    }
