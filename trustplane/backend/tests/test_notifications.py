"""
Tests for Notification models and handler configuration.
"""

from app.models.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationType,
    NotificationCreate,
)
from uuid import uuid4

from app.services.notification_service import NotificationService
from app.services.notification_event_handler import NotificationEventHandler


def test_notification_enums():
    """Ensure notification enums contain expected values."""
    assert NotificationChannel.IN_APP.value == "in_app"
    assert NotificationPriority.CRITICAL.value == "critical"
    assert NotificationStatus.PENDING.value == "pending"
    assert NotificationType.SLA_BREACH.value == "sla.breach"


def test_notification_create_defaults():
    """NotificationCreate defaults are set correctly."""
    create = NotificationCreate(
        recipient_id="user-1",
        notification_type=NotificationType.AGENT_DECISION,
        title="Agent decision",
        message="Decision available",
    )
    
    assert create.channel == NotificationChannel.IN_APP
    assert create.priority == NotificationPriority.NORMAL


def test_notification_service_channel_flags():
    """NotificationService respects channel enablement flags."""
    service = NotificationService(org_id=uuid4())
    assert service._channel_enabled(NotificationChannel.IN_APP) is True


def test_notification_handler_has_event_mappings():
    """NotificationEventHandler has event mappings."""
    handler = NotificationEventHandler()
    assert len(handler._handlers) > 0
