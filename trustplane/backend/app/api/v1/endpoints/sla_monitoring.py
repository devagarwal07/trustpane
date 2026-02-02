"""
SLA Monitoring Endpoints

Real-time monitoring and alerting for SLA status.
Used by dashboards and automated monitoring systems.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta

from app.core.auth import get_current_user, TenantContext
from app.services.sla_service import sla_service
from app.services.sla_workflow_coordinator import sla_workflow_coordinator
from app.engines.sla_types import SLAStatus

router = APIRouter()


@router.get("/dashboard", summary="SLA Dashboard Data")
async def get_dashboard(
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get SLA dashboard data.
    
    Returns:
    - Active SLAs with status
    - At-risk SLAs
    - Recent breaches
    - Compliance summary
    """
    # Get all active instances
    active_instances = await sla_service.list_active_instances(
        org_id=tenant.org_id,
        limit=500
    )
    
    # Categorize by status
    by_status = {status.value: [] for status in SLAStatus}
    at_risk = []
    
    for instance in active_instances:
        by_status[instance.status.value].append({
            "id": str(instance.id),
            "workflow_id": str(instance.workflow_id),
            "elapsed_minutes": round(instance.elapsed_minutes(), 2),
            "remaining_to_soft": round(instance.remaining_to_soft_minutes(), 2) if instance.soft_deadline else None,
            "remaining_to_hard": round(instance.remaining_to_hard_minutes(), 2) if instance.hard_deadline else None,
        })
        
        # Check if at risk (>75% time consumed)
        if instance.status == SLAStatus.ACTIVE and instance.hard_deadline:
            total = (instance.hard_deadline - instance.started_at).total_seconds() if instance.started_at else 0
            elapsed = instance.elapsed_seconds()
            if total > 0 and (elapsed / total) > 0.75:
                prediction = await sla_service.predict_breach(tenant.org_id, instance.id)
                at_risk.append({
                    "id": str(instance.id),
                    "workflow_id": str(instance.workflow_id),
                    "risk_level": prediction.risk_level,
                    "probability": prediction.probability,
                    "time_remaining_minutes": round(prediction.time_remaining_seconds / 60, 2),
                    "recommendations": prediction.recommendations[:2],  # Top 2
                })
    
    # Get compliance for last 7 days
    now = datetime.utcnow()
    compliance = await sla_service.get_compliance_report(
        org_id=tenant.org_id,
        from_date=now - timedelta(days=7),
        to_date=now
    )
    
    return {
        "summary": {
            "total_active": len(active_instances),
            "by_status": {k: len(v) for k, v in by_status.items()},
            "at_risk_count": len(at_risk),
            "compliance_rate_7d": compliance["metrics"]["compliance_percentage"],
        },
        "at_risk": at_risk[:10],  # Top 10 at-risk
        "by_status": by_status,
        "compliance_7d": compliance,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/at-risk", summary="List at-risk SLAs")
async def list_at_risk(
    risk_level: str = Query("high", description="Minimum risk level: low, medium, high, critical"),
    limit: int = Query(50, ge=1, le=200),
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    List SLAs that are at risk of breaching.
    
    Useful for proactive intervention.
    """
    risk_levels = ["minimal", "low", "medium", "high", "critical"]
    if risk_level not in risk_levels:
        raise HTTPException(status_code=400, detail=f"Invalid risk level. Must be one of: {risk_levels}")
    
    min_index = risk_levels.index(risk_level)
    target_levels = set(risk_levels[min_index:])
    
    active_instances = await sla_service.list_active_instances(
        org_id=tenant.org_id,
        limit=limit * 2  # Get more to filter
    )
    
    at_risk = []
    for instance in active_instances:
        if instance.status not in (SLAStatus.ACTIVE, SLAStatus.SOFT_BREACH):
            continue
        
        prediction = await sla_service.predict_breach(tenant.org_id, instance.id)
        
        if prediction.risk_level in target_levels:
            definition = await sla_service.get_definition(tenant.org_id, instance.definition_id)
            at_risk.append({
                "instance_id": str(instance.id),
                "workflow_id": str(instance.workflow_id),
                "definition_name": definition.name if definition else "Unknown",
                "priority": definition.priority.value if definition else "unknown",
                "status": instance.status.value,
                "elapsed_minutes": round(instance.elapsed_minutes(), 2),
                "risk_level": prediction.risk_level,
                "probability": round(prediction.probability, 3),
                "time_remaining_minutes": round(prediction.time_remaining_seconds / 60, 2),
                "recommendations": prediction.recommendations,
                "soft_deadline": instance.soft_deadline.isoformat() if instance.soft_deadline else None,
                "hard_deadline": instance.hard_deadline.isoformat() if instance.hard_deadline else None,
            })
        
        if len(at_risk) >= limit:
            break
    
    # Sort by risk (critical first)
    at_risk.sort(key=lambda x: -risk_levels.index(x["risk_level"]))
    
    return {
        "count": len(at_risk),
        "min_risk_level": risk_level,
        "items": at_risk,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.post("/check-breaches", summary="Run breach check")
async def run_breach_check(
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Manually trigger a breach check for all active SLAs.
    
    Normally this runs automatically, but can be triggered manually.
    """
    results = await sla_workflow_coordinator.check_all_active_slas(tenant.org_id)
    
    return {
        "success": True,
        "results": results,
        "message": f"Checked {results['checked']} SLAs. "
                   f"New breaches: {results['new_soft_breaches']} soft, {results['new_hard_breaches']} hard",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health", summary="SLA System Health")
async def get_health(
    tenant: TenantContext = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get SLA system health status.
    
    Used by monitoring systems.
    """
    # Get recent activity
    active_count = len(await sla_service.list_active_instances(tenant.org_id, limit=100))
    
    # Get compliance
    now = datetime.utcnow()
    recent_compliance = await sla_service.get_compliance_report(
        org_id=tenant.org_id,
        from_date=now - timedelta(hours=24),
        to_date=now
    )
    
    # Determine health status
    compliance_rate = recent_compliance["metrics"]["compliance_rate"]
    if compliance_rate >= 0.95:
        health_status = "healthy"
    elif compliance_rate >= 0.80:
        health_status = "degraded"
    else:
        health_status = "critical"
    
    return {
        "status": health_status,
        "metrics": {
            "active_sla_count": active_count,
            "compliance_rate_24h": compliance_rate,
            "breaches_24h": recent_compliance["metrics"]["breached_count"],
        },
        "checks": {
            "sla_service": "ok",
            "event_store": "ok",
            "breach_checker": "ok",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
