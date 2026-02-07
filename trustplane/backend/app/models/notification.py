"""
Notification models

Defines notification types, channels, and data structures.
"""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from enum import Enum
from pydantic import Field

from app.models.base import BaseModel, TimestampMixin, TenantMixin


class NotificationChannel(str, Enum):
    """Delivery channels for notifications."""
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationPriority(str, Enum):
    """Priority levels for notifications."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationStatus(str, Enum):
    """Delivery status for notifications."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"
    CANCELLED = "cancelled"


class NotificationType(str, Enum):
    """Types of notifications supported by the system."""
    SLA_WARNING = "sla.warning"
    SLA_BREACH = "sla.breach"
    AGENT_DECISION = "agent.decision"
    WORKFLOW_ESCALATED = "workflow.escalated"
    WORKFLOW_ASSIGNED = "workflow.assigned"
    WORKFLOW_COMPLETED = "workflow.completed"


class NotificationCreate(BaseModel):
    """Notification creation payload."""
    recipient_id: str
    channel: NotificationChannel = NotificationChannel.IN_APP
    notification_type: NotificationType
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NotificationRecord(BaseModel, TenantMixin, TimestampMixin):
    """Notification record stored in the database."""
    id: UUID = Field(default_factory=uuid4)
    recipient_id: str
    channel: NotificationChannel
    notification_type: NotificationType
    title: str
    message: str
    priority: NotificationPriority
    status: NotificationStatus = NotificationStatus.PENDING
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    error_message: Optional[str] = None


class NotificationQuery(BaseModel):
    """Notification query filters."""
    status: Optional[NotificationStatus] = None
    notification_type: Optional[NotificationType] = None
    channel: Optional[NotificationChannel] = None
    unread_only: bool = False
    limit: int = 50
    offset: int = 0
