"""
Event store endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, List, Optional
from uuid import UUID
from datetime import datetime

from app.api.deps import (
    get_tenant_context,
    require_permission,
    TenantContext,
)
from app.services.event_store import event_store
from app.engines.integrity_engine import integrity_engine
from app.models.event import EventType
from app.schemas.responses import APIResponse, PaginatedResponse

router = APIRouter()


@router.get("/")
async def list_events(
    stream_id: Optional[UUID] = Query(None, description="Filter by stream ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tenant: TenantContext = Depends(require_permission("event:read"))
) -> Dict[str, Any]:
    """
    List events for the organization.
    
    Optionally filter by stream_id or event_type.
    Events are returned in reverse chronological order.
    """
    try:
        if stream_id:
            # Get events for specific stream
            events = await event_store.get_stream(tenant.org_id, stream_id)
            # Apply pagination
            paginated = events[offset:offset + limit]
            
            return {
                "success": True,
                "data": {
                    "items": [_event_to_dict(e) for e in paginated],
                    "total": len(events),
                    "page": offset // limit + 1,
                    "page_size": limit,
                    "has_more": offset + limit < len(events),
                },
                "timestamp": datetime.utcnow(),
            }
        
        elif event_type:
            # Get events by type
            try:
                et = EventType(event_type)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid event type: {event_type}"
                )
            
            events = await event_store.get_events_by_type(
                tenant.org_id, et, limit, offset
            )
            
            return {
                "success": True,
                "data": {
                    "items": [_event_to_dict(e) for e in events],
                    "page": offset // limit + 1,
                    "page_size": limit,
                },
                "timestamp": datetime.utcnow(),
            }
        
        else:
            # No filter - not supported for performance reasons
            raise HTTPException(
                status_code=400,
                detail="Please provide stream_id or event_type filter"
            )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list events: {str(e)}"
        )


@router.get("/{event_id}")
async def get_event(
    event_id: UUID,
    tenant: TenantContext = Depends(require_permission("event:read"))
) -> Dict[str, Any]:
    """Get a specific event by ID"""
    event = await event_store.get_event(tenant.org_id, event_id)
    
    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )
    
    return {
        "success": True,
        "data": _event_to_dict(event),
        "timestamp": datetime.utcnow(),
    }


@router.get("/stream/{stream_id}")
async def get_event_stream(
    stream_id: UUID,
    from_version: int = Query(0, ge=0),
    to_version: Optional[int] = Query(None, ge=1),
    tenant: TenantContext = Depends(require_permission("event:read"))
) -> Dict[str, Any]:
    """
    Get all events for a specific stream (e.g., workflow).
    
    Events are returned in version order (oldest first).
    This is the foundation for event replay.
    """
    events = await event_store.get_stream(
        tenant.org_id, 
        stream_id,
        from_version,
        to_version
    )
    
    return {
        "success": True,
        "data": {
            "stream_id": str(stream_id),
            "events": [_event_to_dict(e) for e in events],
            "event_count": len(events),
            "first_version": events[0].version if events else None,
            "last_version": events[-1].version if events else None,
        },
        "timestamp": datetime.utcnow(),
    }


@router.post("/stream/{stream_id}/verify")
async def verify_stream_integrity(
    stream_id: UUID,
    tenant: TenantContext = Depends(require_permission("event:verify"))
) -> Dict[str, Any]:
    """
    Verify hash chain integrity for a stream.
    
    This is a CRITICAL security operation that verifies:
    1. No events have been modified (hash verification)
    2. No events have been deleted (chain continuity)
    3. No events have been inserted out of order
    
    Returns a detailed integrity report.
    """
    # Get integrity report from event store
    report = await event_store.verify_integrity(tenant.org_id, stream_id)
    
    return {
        "success": True,
        "data": report,
        "timestamp": datetime.utcnow(),
    }


@router.get("/stream/{stream_id}/timeline")
async def get_stream_timeline(
    stream_id: UUID,
    tenant: TenantContext = Depends(require_permission("event:read"))
) -> Dict[str, Any]:
    """
    Get a human-readable timeline of events for a stream.
    
    Useful for audit UI and debugging.
    """
    events = await event_store.get_stream(tenant.org_id, stream_id)
    
    timeline = []
    for event in events:
        timeline.append({
            "version": event.version,
            "event_type": event.event_type.value,
            "occurred_at": event.occurred_at.isoformat() if isinstance(event.occurred_at, datetime) else event.occurred_at,
            "actor_type": event.actor_type,
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "summary": _get_event_summary(event),
            "hash_prefix": event.hash[:12] + "...",
        })
    
    return {
        "success": True,
        "data": {
            "stream_id": str(stream_id),
            "timeline": timeline,
            "event_count": len(timeline),
        },
        "timestamp": datetime.utcnow(),
    }


@router.get("/stream/{stream_id}/certificate")
async def get_integrity_certificate(
    stream_id: UUID,
    tenant: TenantContext = Depends(require_permission("event:verify"))
) -> Dict[str, Any]:
    """
    Generate an integrity certificate for a stream.
    
    This certificate proves the integrity of the event stream
    at a point in time. Can be used for compliance reporting.
    """
    events = await event_store.get_stream(tenant.org_id, stream_id)
    
    # Convert to dicts for integrity engine
    event_dicts = [
        {
            "id": str(e.id),
            "version": e.version,
            "hash": e.hash,
            "previous_hash": e.previous_hash,
            "occurred_at": e.occurred_at.isoformat() if isinstance(e.occurred_at, datetime) else e.occurred_at,
            "event_type": e.event_type.value,
            "data": e.data,
        }
        for e in events
    ]
    
    certificate = integrity_engine.generate_integrity_certificate(
        str(stream_id),
        event_dicts
    )
    
    return {
        "success": True,
        "data": certificate,
        "timestamp": datetime.utcnow(),
    }


def _event_to_dict(event) -> Dict[str, Any]:
    """Convert Event model to dictionary"""
    return {
        "id": str(event.id),
        "stream_id": str(event.stream_id),
        "event_type": event.event_type.value,
        "version": event.version,
        "data": event.data,
        "metadata": event.metadata,
        "hash": event.hash,
        "previous_hash": event.previous_hash,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_type": event.actor_type,
        "occurred_at": event.occurred_at.isoformat() if isinstance(event.occurred_at, datetime) else event.occurred_at,
        "recorded_at": event.recorded_at.isoformat() if isinstance(event.recorded_at, datetime) else event.recorded_at,
    }


def _get_event_summary(event) -> str:
    """Generate human-readable summary of event"""
    summaries = {
        EventType.WORKFLOW_CREATED: lambda e: f"Workflow created: {e.data.get('name', 'unnamed')}",
        EventType.WORKFLOW_TRANSITIONED: lambda e: f"State: {e.data.get('from_state')} → {e.data.get('to_state')}",
        EventType.WORKFLOW_COMPLETED: lambda e: "Workflow completed",
        EventType.WORKFLOW_FAILED: lambda e: f"Workflow failed: {e.data.get('reason', 'unknown')}",
        EventType.SLA_STARTED: lambda e: "SLA tracking started",
        EventType.SLA_PAUSED: lambda e: f"SLA paused: {e.data.get('reason', 'no reason')}",
        EventType.SLA_RESUMED: lambda e: "SLA resumed",
        EventType.SLA_SOFT_BREACH: lambda e: "⚠️ SLA soft breach",
        EventType.SLA_HARD_BREACH: lambda e: "🚨 SLA hard breach",
        EventType.SLA_MET: lambda e: "✅ SLA met",
        EventType.AGENT_DECISION: lambda e: f"AI decision: {e.data.get('decision', 'unknown')}",
        EventType.AGENT_ESCALATION: lambda e: "Escalated to human review",
        EventType.POLICY_EVALUATED: lambda e: f"Policy: {e.data.get('result', 'evaluated')}",
        EventType.POLICY_VIOLATION: lambda e: f"Policy violation: {e.data.get('policy', 'unknown')}",
    }
    
    handler = summaries.get(event.event_type, lambda e: event.event_type.value)
    return handler(event)
