"""
SLA Management API Endpoints

REST API for managing SLA definitions, instances, and compliance.

Endpoints:
    - Definitions: CRUD for SLA templates (P1-P4 incidents, etc.)
    - Instances: Lifecycle management (create, start, pause, resume, complete)
    - Monitoring: Breach checking, predictions, compliance reports
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from app.core.auth import get_current_user, TenantContext
from app.services.sla_service import sla_service
from app.engines.sla_types import SLAPriority, SLAStatus

router = APIRouter()


# =========================================================
# REQUEST/RESPONSE MODELS
# =========================================================

class SLADefinitionCreate(BaseModel):
    """Request to create an SLA definition"""
    name: str = Field(..., min_length=1, max_length=100, description="SLA name")
    soft_limit_minutes: int = Field(..., gt=0, description="Soft limit in minutes")
    hard_limit_minutes: int = Field(..., gt=0, description="Hard limit in minutes")
    priority: str = Field(default="p3", description="Priority: p1, p2, p3, p4")
    description: Optional[str] = Field(None, max_length=500)
    business_hours_only: bool = Field(default=False, description="Only count business hours")
    business_hours_config: Optional[Dict[str, Any]] = Field(None, description="Business hours settings")
    excluded_states: Optional[List[str]] = Field(None, description="Workflow states where timer pauses")
    escalation_config: Optional[Dict[str, Any]] = Field(None, description="Escalation settings")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Critical Incident SLA",
                "soft_limit_minutes": 15,
                "hard_limit_minutes": 30,
                "priority": "p1",
                "description": "SLA for critical production incidents",
                "business_hours_only": False,
                "excluded_states": ["paused", "waiting_customer"]
            }
        }


class SLAFromTemplateCreate(BaseModel):
    """Create SLA from predefined template"""
    template_name: str = Field(..., description="Template: p1_critical, p2_high, p3_medium, p4_low")
    name_override: Optional[str] = Field(None, description="Custom name")
    soft_limit_minutes: Optional[int] = Field(None, gt=0, description="Override soft limit")
    hard_limit_minutes: Optional[int] = Field(None, gt=0, description="Override hard limit")


class SLAInstanceCreate(BaseModel):
    """Request to create an SLA instance"""
    definition_id: UUID = Field(..., description="SLA definition to use")
    workflow_id: UUID = Field(..., description="Workflow to track")
    auto_start: bool = Field(default=True, description="Start timer immediately")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SLAPauseRequest(BaseModel):
    """Request to pause an SLA"""
    reason: str = Field(..., min_length=1, max_length=500, description="Pause reason")


class SLACompleteRequest(BaseModel):
    """Request to complete an SLA"""
    resolution: Optional[str] = Field(None, max_length=500, description="Resolution notes")


class SLACancelRequest(BaseModel):
    """Request to cancel an SLA"""
    reason: str = Field(..., min_length=1, max_length=500, description="Cancellation reason")


# =========================================================
# DEFINITION ENDPOINTS
# =========================================================

@router.get("/definitions", summary="List SLA definitions")
async def list_sla_definitions(
    include_archived: bool = Query(False, description="Include archived definitions"),
    tenant: TenantContext = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    List all SLA definitions for the organization.
    
    Returns templates that can be attached to workflows.
    """
    definitions = await sla_service.list_definitions(
        org_id=tenant.org_id,
        include_archived=include_archived
    )
    return [d.to_dict() for d in definitions]


@router.post("/definitions", status_code=status.HTTP_201_CREATED, summary="Create SLA definition")
async def create_sla_definition(
    request: SLADefinitionCreate,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Create a new SLA definition.
    
    SLA definitions are templates with soft/hard limits, business hours rules,
    and escalation configurations. Attach them to workflows via instances.
    """
    # Validate hard > soft
    if request.hard_limit_minutes <= request.soft_limit_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hard_limit_minutes must be greater than soft_limit_minutes"
        )
    
    try:
        priority = SLAPriority(request.priority.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid priority. Must be one of: {[p.value for p in SLAPriority]}"
        )
    
    definition = await sla_service.create_definition(
        org_id=tenant.org_id,
        name=request.name,
        soft_limit_minutes=request.soft_limit_minutes,
        hard_limit_minutes=request.hard_limit_minutes,
        actor_id=tenant.user_id,
        priority=priority,
        description=request.description,
        business_hours_only=request.business_hours_only,
        business_hours_config=request.business_hours_config,
        excluded_states=request.excluded_states,
        escalation_config=request.escalation_config,
        metadata=request.metadata
    )
    
    return definition.to_dict()


@router.post("/definitions/from-template", status_code=status.HTTP_201_CREATED, summary="Create from template")
async def create_from_template(
    request: SLAFromTemplateCreate,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Create SLA definition from a predefined template.
    
    Templates:
    - p1_critical: 15min soft / 30min hard (24/7)
    - p2_high: 1hr soft / 2hr hard (24/7)
    - p3_medium: 4hr soft / 8hr hard (business hours)
    - p4_low: 24hr soft / 48hr hard (business hours)
    """
    try:
        overrides = {}
        if request.soft_limit_minutes:
            overrides["soft_limit_minutes"] = request.soft_limit_minutes
        if request.hard_limit_minutes:
            overrides["hard_limit_minutes"] = request.hard_limit_minutes
        
        definition = await sla_service.create_definition_from_template(
            org_id=tenant.org_id,
            template_name=request.template_name,
            actor_id=tenant.user_id,
            name_override=request.name_override,
            **overrides
        )
        return definition.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/definitions/{definition_id}", summary="Get SLA definition")
async def get_sla_definition(
    definition_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get SLA definition details."""
    definition = await sla_service.get_definition(
        org_id=tenant.org_id,
        definition_id=definition_id
    )
    
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA definition not found"
        )
    
    return definition.to_dict()


# =========================================================
# INSTANCE ENDPOINTS
# =========================================================

@router.get("/instances", summary="List SLA instances")
async def list_sla_instances(
    workflow_id: Optional[UUID] = Query(None, description="Filter by workflow"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    tenant: TenantContext = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    List SLA instances.
    
    Can filter by workflow or status (pending, active, soft_breach, hard_breach, met, cancelled).
    """
    if workflow_id:
        instances = await sla_service.get_instances_for_workflow(
            org_id=tenant.org_id,
            workflow_id=workflow_id
        )
    else:
        instances = await sla_service.list_active_instances(
            org_id=tenant.org_id,
            limit=limit
        )
    
    # Apply status filter if provided
    if status_filter:
        try:
            target_status = SLAStatus(status_filter.lower())
            instances = [i for i in instances if i.status == target_status]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {[s.value for s in SLAStatus]}"
            )
    
    return [i.to_dict() for i in instances]


@router.post("/instances", status_code=status.HTTP_201_CREATED, summary="Create SLA instance")
async def create_sla_instance(
    request: SLAInstanceCreate,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Create a new SLA instance for a workflow.
    
    The SLA timer starts immediately if auto_start=True (default).
    """
    try:
        instance = await sla_service.create_instance(
            org_id=tenant.org_id,
            definition_id=request.definition_id,
            workflow_id=request.workflow_id,
            actor_id=tenant.user_id,
            auto_start=request.auto_start,
            metadata=request.metadata
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/instances/{instance_id}", summary="Get SLA instance")
async def get_sla_instance(
    instance_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """Get SLA instance details with current timing info."""
    instance = await sla_service.get_instance(
        org_id=tenant.org_id,
        instance_id=instance_id
    )
    
    if not instance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLA instance not found"
        )
    
    result = instance.to_dict()
    
    # Add real-time calculations
    result["elapsed_minutes"] = round(instance.elapsed_minutes(), 2)
    result["remaining_to_soft_minutes"] = round(instance.remaining_to_soft_minutes(), 2) if instance.soft_deadline else None
    result["remaining_to_hard_minutes"] = round(instance.remaining_to_hard_minutes(), 2) if instance.hard_deadline else None
    
    return result


@router.post("/instances/{instance_id}/start", summary="Start SLA timer")
async def start_sla_instance(
    instance_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """Start the SLA timer (for instances created with auto_start=False)."""
    try:
        instance = await sla_service.start_sla(
            org_id=tenant.org_id,
            instance_id=instance_id,
            actor_id=tenant.user_id
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/instances/{instance_id}/pause", summary="Pause SLA timer")
async def pause_sla_instance(
    instance_id: UUID,
    request: SLAPauseRequest,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Pause the SLA timer.
    
    Use when workflow is blocked on external factors (waiting on customer, etc.).
    Time while paused does NOT count toward SLA limits.
    """
    try:
        instance = await sla_service.pause_sla(
            org_id=tenant.org_id,
            instance_id=instance_id,
            reason=request.reason,
            actor_id=tenant.user_id
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/instances/{instance_id}/resume", summary="Resume SLA timer")
async def resume_sla_instance(
    instance_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """Resume a paused SLA timer."""
    try:
        instance = await sla_service.resume_sla(
            org_id=tenant.org_id,
            instance_id=instance_id,
            actor_id=tenant.user_id
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/instances/{instance_id}/complete", summary="Complete SLA")
async def complete_sla_instance(
    instance_id: UUID,
    request: SLACompleteRequest,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Complete the SLA (workflow finished).
    
    Final status (MET or BREACHED) is determined by elapsed time vs limits.
    """
    try:
        instance = await sla_service.complete_sla(
            org_id=tenant.org_id,
            instance_id=instance_id,
            actor_id=tenant.user_id,
            resolution=request.resolution
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/instances/{instance_id}/cancel", summary="Cancel SLA")
async def cancel_sla_instance(
    instance_id: UUID,
    request: SLACancelRequest,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """Cancel an SLA (workflow cancelled, SLA no longer applicable)."""
    try:
        instance = await sla_service.cancel_sla(
            org_id=tenant.org_id,
            instance_id=instance_id,
            reason=request.reason,
            actor_id=tenant.user_id
        )
        return instance.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# =========================================================
# MONITORING ENDPOINTS
# =========================================================

@router.get("/instances/{instance_id}/breach-status", summary="Check breach status")
async def check_breach_status(
    instance_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Check current breach status for an SLA instance.
    
    Returns whether soft/hard limits have been exceeded and by how much.
    """
    try:
        result = await sla_service.check_breach(
            org_id=tenant.org_id,
            instance_id=instance_id
        )
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/instances/{instance_id}/predict", summary="Predict breach likelihood")
async def predict_breach(
    instance_id: UUID,
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Predict likelihood of SLA breach.
    
    Returns probability, risk level, and actionable recommendations.
    """
    try:
        prediction = await sla_service.predict_breach(
            org_id=tenant.org_id,
            instance_id=instance_id
        )
        return prediction.to_dict()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/compliance", summary="Get compliance report")
async def get_compliance_report(
    from_date: Optional[datetime] = Query(None, description="Start date (default: 30 days ago)"),
    to_date: Optional[datetime] = Query(None, description="End date (default: now)"),
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Generate SLA compliance report for a time period.
    
    Returns aggregated metrics: compliance rate, average times, breach counts.
    """
    # Default to last 30 days
    if not to_date:
        to_date = datetime.utcnow()
    if not from_date:
        from_date = to_date - timedelta(days=30)
    
    report = await sla_service.get_compliance_report(
        org_id=tenant.org_id,
        from_date=from_date,
        to_date=to_date
    )
    
    return report


@router.get("/templates", summary="List available templates")
async def list_templates() -> Dict[str, Any]:
    """
    List available SLA templates.
    
    Templates provide sensible defaults for common incident priorities.
    """
    from app.engines.sla_types import DEFAULT_SLA_TEMPLATES
    return {
        "templates": DEFAULT_SLA_TEMPLATES,
        "description": "Use POST /definitions/from-template to create from these templates"
    }
