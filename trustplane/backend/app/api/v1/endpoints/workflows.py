"""
Workflow management endpoints

Event-sourced workflow API:
- Create workflows (emits WORKFLOW_CREATED event)
- Transition states (emits WORKFLOW_TRANSITIONED event)
- Query current state (derived from events)
- Time travel to past states
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime

from app.api.deps import (
    get_tenant_context,
    require_permission,
    TenantContext,
)
from app.services.workflow_service import (
    workflow_service,
    WorkflowState,
    WorkflowType,
    WorkflowStateMachine,
)
from app.core.exceptions import ValidationError

router = APIRouter()


# =========================================================
# REQUEST/RESPONSE SCHEMAS
# =========================================================

class WorkflowCreateRequest(BaseModel):
    """Create workflow request"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    workflow_type: str = Field(default="custom")
    config: Dict[str, Any] = Field(default_factory=dict)
    sla_definition_id: Optional[UUID] = None
    idempotency_key: Optional[str] = Field(None, max_length=255)


class WorkflowTransitionRequest(BaseModel):
    """Transition workflow state request"""
    to_state: str
    reason: Optional[str] = Field(None, max_length=1000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowActionRequest(BaseModel):
    """Simple workflow action request"""
    reason: Optional[str] = Field(None, max_length=1000)


# =========================================================
# ENDPOINTS
# =========================================================

@router.get("/")
async def list_workflows(
    state: Optional[str] = Query(None, description="Filter by state"),
    workflow_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(require_permission("workflow:read"))
) -> Dict[str, Any]:
    """
    List workflows for current organization.
    
    Returns paginated list with current state (derived from events).
    """
    try:
        # Parse filters
        state_filter = WorkflowState(state) if state else None
        type_filter = WorkflowType(workflow_type) if workflow_type else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    workflows = await workflow_service.list_workflows(
        tenant.org_id,
        state_filter=state_filter,
        workflow_type=type_filter,
        limit=limit,
        offset=offset
    )
    
    return {
        "success": True,
        "data": {
            "items": [w.to_dict() for w in workflows],
            "count": len(workflows),
            "page": offset // limit + 1,
            "page_size": limit,
        },
        "timestamp": datetime.utcnow(),
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowCreateRequest,
    tenant: TenantContext = Depends(require_permission("workflow:create"))
) -> Dict[str, Any]:
    """
    Create a new workflow.
    
    Emits a WORKFLOW_CREATED event. Workflow starts in 'pending' state.
    """
    try:
        wf_type = WorkflowType(request.workflow_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workflow type: {request.workflow_type}"
        )
    
    try:
        workflow = await workflow_service.create_workflow(
            org_id=tenant.org_id,
            name=request.name,
            workflow_type=wf_type,
            actor_id=tenant.user_id,
            description=request.description,
            config=request.config,
            sla_definition_id=request.sla_definition_id,
            idempotency_key=request.idempotency_key,
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow created successfully",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: UUID,
    version: Optional[int] = Query(None, description="Get state at specific version"),
    tenant: TenantContext = Depends(require_permission("workflow:read"))
) -> Dict[str, Any]:
    """
    Get workflow details.
    
    State is derived by replaying all events.
    Optionally get state at a specific version (time travel).
    """
    if version is not None:
        workflow = await workflow_service.get_workflow_at_version(
            tenant.org_id, workflow_id, version
        )
    else:
        workflow = await workflow_service.get_workflow(tenant.org_id, workflow_id)
    
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not found: {workflow_id}"
        )
    
    return {
        "success": True,
        "data": workflow.to_dict(),
        "timestamp": datetime.utcnow(),
    }


@router.post("/{workflow_id}/transition")
async def transition_workflow(
    workflow_id: UUID,
    request: WorkflowTransitionRequest,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """
    Transition workflow to a new state.
    
    Validates the transition against the state machine rules.
    Emits a WORKFLOW_TRANSITIONED event.
    """
    try:
        to_state = WorkflowState(request.to_state)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid state: {request.to_state}"
        )
    
    try:
        workflow = await workflow_service.transition(
            org_id=tenant.org_id,
            workflow_id=workflow_id,
            to_state=to_state,
            actor_id=tenant.user_id,
            reason=request.reason,
            metadata=request.metadata,
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": f"Workflow transitioned to '{to_state.value}'",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workflow_id}/transitions")
async def get_allowed_transitions(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflow:read"))
) -> Dict[str, Any]:
    """
    Get allowed transitions for workflow's current state.
    
    Useful for UI to show available actions.
    """
    try:
        transitions = await workflow_service.get_allowed_transitions(
            tenant.org_id, workflow_id
        )
        
        return {
            "success": True,
            "data": transitions,
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =========================================================
# CONVENIENCE ENDPOINTS (shortcuts for common transitions)
# =========================================================

@router.post("/{workflow_id}/start")
async def start_workflow(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Start a pending workflow (transition to 'active')"""
    try:
        workflow = await workflow_service.start(
            tenant.org_id, workflow_id, tenant.user_id
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow started",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/pause")
async def pause_workflow(
    workflow_id: UUID,
    request: WorkflowActionRequest,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Pause an active workflow"""
    try:
        workflow = await workflow_service.pause(
            tenant.org_id, workflow_id, tenant.user_id,
            reason=request.reason
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow paused",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/resume")
async def resume_workflow(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Resume a paused workflow"""
    try:
        workflow = await workflow_service.resume(
            tenant.org_id, workflow_id, tenant.user_id
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow resumed",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/complete")
async def complete_workflow(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Complete a workflow successfully"""
    try:
        workflow = await workflow_service.complete(
            tenant.org_id, workflow_id, tenant.user_id
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow completed",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/fail")
async def fail_workflow(
    workflow_id: UUID,
    request: WorkflowActionRequest,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Mark a workflow as failed (requires reason)"""
    if not request.reason:
        raise HTTPException(
            status_code=400,
            detail="Reason is required when failing a workflow"
        )
    
    try:
        workflow = await workflow_service.fail(
            tenant.org_id, workflow_id, tenant.user_id,
            reason=request.reason
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow marked as failed",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(
    workflow_id: UUID,
    request: WorkflowActionRequest,
    tenant: TenantContext = Depends(require_permission("workflow:transition"))
) -> Dict[str, Any]:
    """Cancel a workflow (requires reason)"""
    if not request.reason:
        raise HTTPException(
            status_code=400,
            detail="Reason is required when cancelling a workflow"
        )
    
    try:
        workflow = await workflow_service.cancel(
            tenant.org_id, workflow_id, tenant.user_id,
            reason=request.reason
        )
        
        return {
            "success": True,
            "data": workflow.to_dict(),
            "message": "Workflow cancelled",
            "timestamp": datetime.utcnow(),
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{workflow_id}/timeline")
async def get_workflow_timeline(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflow:read"))
) -> Dict[str, Any]:
    """
    Get workflow state timeline (history of transitions).
    
    Useful for audit and debugging.
    """
    workflow = await workflow_service.get_workflow(tenant.org_id, workflow_id)
    
    if not workflow:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not found: {workflow_id}"
        )
    
    return {
        "success": True,
        "data": {
            "workflow_id": str(workflow_id),
            "current_state": workflow.current_state.value,
            "is_terminal": workflow.is_terminal(),
            "timeline": workflow.state_history,
            "event_count": workflow.event_count,
        },
        "timestamp": datetime.utcnow(),
    }


# =========================================================
# STATE MACHINE INFO
# =========================================================

@router.get("/state-machine/transitions")
async def get_state_machine_info(
    tenant: TenantContext = Depends(require_permission("workflow:read"))
) -> Dict[str, Any]:
    """
    Get state machine definition.
    
    Returns all states and valid transitions.
    Useful for documentation and UI rendering.
    """
    transitions = {}
    
    for state in WorkflowState:
        allowed = WorkflowStateMachine.get_allowed_transitions(state)
        transitions[state.value] = {
            "allowed_targets": [s.value for s in allowed],
            "is_terminal": len(allowed) == 0,
            "transitions": [
                {
                    "to": s.value,
                    "requires_reason": WorkflowStateMachine.requires_reason(state, s),
                }
                for s in allowed
            ],
        }
    
    return {
        "success": True,
        "data": {
            "states": [s.value for s in WorkflowState],
            "terminal_states": ["completed", "failed", "cancelled"],
            "initial_state": "pending",
            "transitions": transitions,
            "workflow_types": [t.value for t in WorkflowType],
        },
        "timestamp": datetime.utcnow(),
    }
