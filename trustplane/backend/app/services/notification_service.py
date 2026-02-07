"""
Notification Service

Provides notification delivery and storage:
- Records notifications in database
- Sends via configured channels
- Tracks delivery status and reads
- Integrates with event system
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
import logging

from app.core.config import settings
from app.db.supabase import db
from app.models.notification import (
    NotificationCreate,
    NotificationRecord,
    NotificationStatus,
    NotificationChannel,
    NotificationType,
    NotificationPriority,
    NotificationQuery,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Notification management and delivery.
    
    Stores notifications in the database and optionally
    dispatches them through external channels.
    """
    
    def __init__(self, org_id: UUID):
        self.org_id = org_id
    
    async def create_notification(
        self,
        payload: NotificationCreate,
        auto_send: bool = True,
    ) -> NotificationRecord:
        """Create a notification record and optionally send it."""
        record = NotificationRecord(
            org_id=self.org_id,
            recipient_id=payload.recipient_id,
            channel=payload.channel,
            notification_type=payload.notification_type,
            title=payload.title,
            message=payload.message,
            priority=payload.priority,
            payload=payload.payload,
            metadata=payload.metadata,
        )
        
        await self._insert_record(record)
        
        if auto_send:
            record = await self.send_notification(record)
        
        return record
    
    async def send_notification(self, record: NotificationRecord) -> NotificationRecord:
        """
        Dispatch a notification through its channel.
        
        Current implementation stores delivery status and simulates
        external delivery. Real integrations can be added later.
        """
        enabled = self._channel_enabled(record.channel)
        
        if not enabled:
            record.status = NotificationStatus.FAILED
            record.error_message = f"Channel {record.channel.value} not enabled"
            await self._update_status(record)
            return record
        
        # Simulate delivery success
        record.status = NotificationStatus.SENT
        record.sent_at = datetime.utcnow()
        record.error_message = None
        await self._update_status(record)
        
        logger.info(
            f"Notification sent: {record.notification_type.value} -> {record.channel.value}",
            extra={"notification_id": str(record.id), "recipient_id": record.recipient_id}
        )
        
        return record
    
    async def mark_read(self, notification_id: UUID) -> bool:
        """Mark notification as read."""
        now = datetime.utcnow()
        result = await db.update(
            table="notifications",
            data={
                "status": NotificationStatus.READ.value,
                "read_at": now,
                "updated_at": now,
            },
            filters={"id": str(notification_id), "org_id": str(self.org_id)}
        )
        return bool(result.data)
    
    async def mark_all_read(self, recipient_id: str) -> int:
        """Mark all notifications as read for a recipient."""
        now = datetime.utcnow()
        result = await db.update(
            table="notifications",
            data={
                "status": NotificationStatus.READ.value,
                "read_at": now,
                "updated_at": now,
            },
            filters={"org_id": str(self.org_id), "recipient_id": recipient_id}
        )
        return len(result.data) if result.data else 0
    
    async def list_notifications(
        self,
        recipient_id: str,
        query: Optional[NotificationQuery] = None,
    ) -> List[Dict[str, Any]]:
        """List notifications for a recipient with filters."""
        query = query or NotificationQuery()
        
        filters = {
            "org_id": str(self.org_id),
            "recipient_id": recipient_id,
        }
        if query.status:
            filters["status"] = query.status.value
        if query.notification_type:
            filters["notification_type"] = query.notification_type.value
        if query.channel:
            filters["channel"] = query.channel.value
        
        result = await db.query(
            table="notifications",
            select="*",
            filters=filters,
        )
        
        rows = result.data or []
        
        if query.unread_only:
            rows = [r for r in rows if r.get("status") != NotificationStatus.READ.value]
        
        # Sort by created_at descending (if available)
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        
        return rows[query.offset:query.offset + query.limit]
    
    async def _insert_record(self, record: NotificationRecord) -> None:
        """Insert notification record into database."""
        data = {
            "id": str(record.id),
            "org_id": str(record.org_id),
            "recipient_id": record.recipient_id,
            "channel": record.channel.value,
            "notification_type": record.notification_type.value,
            "title": record.title,
            "message": record.message,
            "priority": record.priority.value,
            "status": record.status.value,
            "payload": record.payload,
            "metadata": record.metadata,
            "sent_at": record.sent_at,
            "read_at": record.read_at,
            "error_message": record.error_message,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        
        result = await db.insert("notifications", data)
        if not result.data:
            raise RuntimeError("Failed to create notification")
    
    async def _update_status(self, record: NotificationRecord) -> None:
        """Update notification status in database."""
        data = {
            "status": record.status.value,
            "sent_at": record.sent_at,
            "read_at": record.read_at,
            "error_message": record.error_message,
            "updated_at": datetime.utcnow(),
        }
        
        await db.update(
            table="notifications",
            data=data,
            filters={"id": str(record.id), "org_id": str(self.org_id)}
        )
    
    def _channel_enabled(self, channel: NotificationChannel) -> bool:
        """Check if a channel is enabled via settings."""
        if channel == NotificationChannel.IN_APP:
            return settings.NOTIFICATION_IN_APP_ENABLED
        if channel == NotificationChannel.EMAIL:
            return settings.NOTIFICATION_EMAIL_ENABLED
        if channel == NotificationChannel.SMS:
            return settings.NOTIFICATION_SMS_ENABLED
        if channel == NotificationChannel.WEBHOOK:
            return settings.NOTIFICATION_WEBHOOK_ENABLED
        return False


def create_notification_service(org_id: UUID) -> NotificationService:
    """Factory for notification service."""
    return NotificationService(org_id)


_notification_services: dict[UUID, NotificationService] = {}


def get_notification_service(org_id: UUID) -> NotificationService:
    """Get or create notification service for org."""
    if org_id not in _notification_services:
        _notification_services[org_id] = create_notification_service(org_id)
    return _notification_services[org_id]
