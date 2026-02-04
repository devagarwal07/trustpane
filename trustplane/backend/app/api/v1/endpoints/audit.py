"""
Audit API Endpoints

REST API for audit logging, querying, and compliance reporting.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from app.core.auth import get_current_user, get_current_org_id
from app.models.audit import (
    AuditRecord, AuditCreate, AuditQueryFilter, AuditSummary,
    ComplianceReport, AuditIntegrityCheck, AnomalyDetection,
    AuditEventType, AuditActionType, AuditSeverity
)
from app.services.audit_service import AuditService
from app.core.database import get_supabase


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=dict)
async def list_audit_logs(
    event_type: Optional[AuditEventType] = Query(None),
    actor_id: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    action: Optional[AuditActionType] = Query(None),
    severity: Optional[AuditSeverity] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    List audit logs with optional filters.
    
    Filters:
    - event_type: Type of event (auth.login, workflow.created, etc.)
    - actor_id: User who performed the action
    - target_id: Resource the action was performed on
    - action: Action type (create, read, update, delete, etc.)
    - severity: Event severity (info, warning, error, critical)
    - Date range: start_date and end_date
    """
    service = AuditService(supabase, org_id)
    
    filters = AuditQueryFilter(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        action=action,
        severity=severity,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    
    records, total = await service.query_logs(filters)
    
    return {
        "data": [r.dict() for r in records],
        "pagination": {
            "skip": skip,
            "limit": limit,
            "total": total,
            "has_more": skip + limit < total,
        }
    }


@router.get("/logs/{log_id}", response_model=dict)
async def get_audit_log(
    log_id: UUID,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """Get a specific audit log record."""
    service = AuditService(supabase, org_id)
    
    records, _ = await service.query_logs(
        AuditQueryFilter(
            skip=0,
            limit=1,
        )
    )
    
    # Find the record (in real implementation, query by ID)
    record = None
    for r in records:
        if r.id == log_id:
            record = r
            break
    
    if not record:
        raise HTTPException(status_code=404, detail="Audit log not found")
    
    return record.dict()


@router.post("/logs", response_model=dict, status_code=201)
async def create_audit_log(
    audit: AuditCreate,
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Create an audit log entry.
    
    This is typically called by internal services, not directly by users.
    """
    service = AuditService(supabase, org_id)
    
    record = await service.log_event(audit)
    
    return record.dict()


@router.get("/summary", response_model=dict)
async def get_audit_summary(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Get summary statistics of audit logs.
    
    If no date range provided, defaults to last 30 days.
    """
    service = AuditService(supabase, org_id)
    
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=30)
    
    summary = await service.get_summary(start_date, end_date)
    
    return summary.dict()


@router.get("/compliance-report", response_model=dict)
async def get_compliance_report(
    period_start: Optional[datetime] = Query(None),
    period_end: Optional[datetime] = Query(None),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Generate compliance report for audit trail.
    
    Includes:
    - Retention compliance
    - Integrity verification
    - Sensitive data access tracking
    - User activity summary
    - System change tracking
    - Recommendations
    
    If no date range provided, defaults to last 90 days.
    """
    service = AuditService(supabase, org_id)
    
    if not period_end:
        period_end = datetime.utcnow()
    if not period_start:
        period_start = period_end - timedelta(days=90)
    
    report = await service.generate_compliance_report(period_start, period_end)
    
    return report.dict()


@router.post("/integrity-check", response_model=dict)
async def verify_audit_integrity(
    start_record_id: Optional[UUID] = Query(None),
    end_record_id: Optional[UUID] = Query(None),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Verify integrity of audit chain.
    
    Checks:
    - Hash integrity of all records
    - Chain continuity
    - Missing records
    
    Returns check results with any detected issues.
    """
    service = AuditService(supabase, org_id)
    
    check = await service.verify_integrity(start_record_id, end_record_id)
    
    return check.dict()


@router.get("/anomalies", response_model=dict)
async def detect_anomalies(
    lookback_days: int = Query(7, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Detect anomalies in audit trail.
    
    Detects:
    - Unusual data export patterns
    - Brute force login attempts
    - Privilege escalation attempts
    - Mass deletions
    
    Returns list of detected anomalies with context.
    """
    service = AuditService(supabase, org_id)
    
    anomalies = await service.detect_anomalies(lookback_days)
    
    return {
        "anomalies": [a.dict() for a in anomalies],
        "lookback_days": lookback_days,
        "detected_at": datetime.utcnow().isoformat(),
    }


@router.get("/export/csv", response_model=dict)
async def export_audit_logs_csv(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Export audit logs to CSV format.
    
    Returns CSV data for compliance and archival.
    """
    service = AuditService(supabase, org_id)
    
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=90)
    
    records, _ = await service.query_logs(
        AuditQueryFilter(
            start_date=start_date,
            end_date=end_date,
            limit=100000,
        )
    )
    
    # Convert to CSV
    csv_lines = [
        "id,org_id,event_type,action,severity,actor_id,target_id,description,created_at"
    ]
    
    for record in records:
        csv_line = f"{record.id},{record.org_id},{record.event_type},{record.action}," \
                   f"{record.severity},{record.actor_id},{record.target_id}," \
                   f"\"{record.description}\",{record.created_at.isoformat()}"
        csv_lines.append(csv_line)
    
    return {
        "csv": "\n".join(csv_lines),
        "record_count": len(records),
        "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
    }


@router.get("/events/types", response_model=dict)
async def get_event_types():
    """Get list of all auditable event types."""
    return {
        "event_types": [e.value for e in AuditEventType],
        "total": len(AuditEventType),
    }


@router.get("/actions/types", response_model=dict)
async def get_action_types():
    """Get list of all audit action types."""
    return {
        "action_types": [a.value for a in AuditActionType],
        "total": len(AuditActionType),
    }


@router.get("/severity/levels", response_model=dict)
async def get_severity_levels():
    """Get list of severity levels."""
    return {
        "severity_levels": [s.value for s in AuditSeverity],
        "definitions": {
            "info": "Informational event",
            "warning": "Warning level event",
            "error": "Error condition",
            "critical": "Critical security event",
        }
    }


@router.get("/stats", response_model=dict)
async def get_audit_stats(
    current_user: dict = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),
    supabase = Depends(get_supabase),
):
    """
    Get audit system statistics.
    
    Returns:
    - Total log entries
    - Event types distribution
    - Top actors
    - Severity distribution
    """
    service = AuditService(supabase, org_id)
    
    summary = await service.get_summary(
        datetime.utcnow() - timedelta(days=30),
        datetime.utcnow()
    )
    
    return {
        "last_30_days": {
            "total_events": summary.total_events,
            "by_type": summary.events_by_type,
            "by_actor": summary.events_by_actor,
            "by_severity": summary.events_by_severity,
            "top_events": summary.top_events,
        }
    }
