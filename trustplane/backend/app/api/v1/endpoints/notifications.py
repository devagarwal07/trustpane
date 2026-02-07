"""
Notification Endpoints

In-app notification management for users.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime

from app.api.deps import get_tenant_context, TenantContext
from app.models.notification import (
    NotificationStatus,
    NotificationType,
    NotificationChannel,
    NotificationQuery,
)
from app.services.notification_service import get_notification_service


router = APIRouter()


@router.get("/", summary="List notifications")
async def list_notifications(
    status: Optional[NotificationStatus] = None,
    notification_type: Optional[NotificationType] = None,
    channel: Optional[NotificationChannel] = None,
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """
    List notifications for the current user.
    """
    service = get_notification_service(tenant.org_id)
    query = NotificationQuery(
        status=status,
        notification_type=notification_type,
        channel=channel,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    
    rows = await service.list_notifications(
        recipient_id=str(tenant.user_id),
        query=query,
    )
    
    return {
        "count": len(rows),
        "items": rows,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/{notification_id}", summary="Get notification")
async def get_notification(
    notification_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """
    Get a single notification by ID.
    """
    service = get_notification_service(tenant.org_id)
    rows = await service.list_notifications(
        recipient_id=str(tenant.user_id),
        query=NotificationQuery(limit=200),
    )
    
    notification = next((n for n in rows if n.get("id") == str(notification_id)), None)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {
        "notification": notification,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/{notification_id}/read", summary="Mark notification read")
async def mark_notification_read(
    notification_id: UUID,
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """
    Mark a notification as read.
    """
    service = get_notification_service(tenant.org_id)
    updated = await service.mark_read(notification_id)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {
        "status": "read",
        "notification_id": str(notification_id),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/read-all", summary="Mark all notifications read")
async def mark_all_read(
    tenant: TenantContext = Depends(get_tenant_context),
) -> Dict[str, Any]:
    """
    Mark all notifications as read for the current user.
    """
    service = get_notification_service(tenant.org_id)
    count = await service.mark_all_read(str(tenant.user_id))
    
    return {
        "status": "read_all",
        "count": count,
        "timestamp": datetime.utcnow().isoformat(),
    }
