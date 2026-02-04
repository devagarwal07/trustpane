"""
Audit Models

Data models for audit logging and compliance tracking.
All audit records are immutable and represent the complete audit trail.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Optional
from enum import Enum
from uuid import UUID


class AuditEventType(str, Enum):
    """Types of auditable events."""
    # Authentication
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_FAILED = "auth.failed"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_PERMISSION_DENIED = "auth.permission_denied"
    
    # Workflow operations
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_UPDATED = "workflow.updated"
    WORKFLOW_TRANSITIONED = "workflow.transitioned"
    WORKFLOW_ASSIGNED = "workflow.assigned"
    WORKFLOW_COMMENTED = "workflow.commented"
    WORKFLOW_DELETED = "workflow.deleted"
    
    # SLA operations
    SLA_CREATED = "sla.created"
    SLA_PAUSED = "sla.paused"
    SLA_RESUMED = "sla.resumed"
    SLA_SOFT_BREACH = "sla.soft_breach"
    SLA_HARD_BREACH = "sla.hard_breach"
    SLA_MET = "sla.met"
    SLA_FAILED = "sla.failed"
    
    # Policy operations
    POLICY_CREATED = "policy.created"
    POLICY_UPDATED = "policy.updated"
    POLICY_DELETED = "policy.deleted"
    POLICY_EVALUATED = "policy.evaluated"
    
    # Agent operations
    AGENT_DECISION_MADE = "agent.decision_made"
    AGENT_RECOMMENDATION = "agent.recommendation"
    AGENT_REJECTED = "agent.rejected"
    
    # Data operations
    DATA_EXPORTED = "data.exported"
    DATA_IMPORTED = "data.imported"
    DATA_DELETED = "data.deleted"
    
    # System operations
    SYSTEM_CONFIG_CHANGED = "system.config_changed"
    SYSTEM_BACKUP = "system.backup"
    SYSTEM_ALERT = "system.alert"


class AuditActionType(str, Enum):
    """Type of action in audit record."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    APPROVE = "approve"
    REJECT = "reject"
    EXPORT = "export"
    IMPORT = "import"
    CHANGE = "change"


class AuditSeverity(str, Enum):
    """Severity level of audit event."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditBase(BaseModel):
    """Base audit record model."""
    event_type: AuditEventType
    action: AuditActionType
    severity: AuditSeverity = AuditSeverity.INFO
    
    # Actor (who performed the action)
    actor_id: Optional[str] = None
    actor_type: str = "user"  # user, agent, system
    actor_name: Optional[str] = None
    
    # Target (what was acted upon)
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    target_name: Optional[str] = None
    
    # Context
    resource: Optional[str] = None
    description: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    
    # Change tracking
    changes: Optional[dict[str, Any]] = None
    
    # IP and session
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None


class AuditCreate(AuditBase):
    """Request model for creating audit record."""
    pass


class AuditRecord(AuditBase):
    """Audit record in database."""
    id: UUID
    org_id: UUID
    
    # Immutability hash
    content_hash: str  # SHA-256 of content for integrity
    
    # Timestamps
    created_at: datetime
    retention_until: Optional[datetime] = None
    
    # Compliance
    is_archived: bool = False
    archive_location: Optional[str] = None
    
    class Config:
        from_attributes = True


class AuditQueryFilter(BaseModel):
    """Filters for audit log queries."""
    event_type: Optional[AuditEventType] = None
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    action: Optional[AuditActionType] = None
    severity: Optional[AuditSeverity] = None
    
    # Date range
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    # Pagination
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    
    # Sorting
    sort_by: str = Field(default="created_at")
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class AuditSummary(BaseModel):
    """Summary statistics for audit logs."""
    total_events: int
    date_range_start: datetime
    date_range_end: datetime
    
    # Event counts by type
    events_by_type: dict[str, int]
    
    # Events by actor
    events_by_actor: dict[str, int]
    
    # Events by severity
    events_by_severity: dict[str, int]
    
    # Top events
    top_events: list[dict[str, Any]]


class ComplianceReport(BaseModel):
    """Compliance report for audit trail."""
    org_id: UUID
    report_date: datetime
    period_start: datetime
    period_end: datetime
    
    # Retention compliance
    total_records: int
    compliant_records: int
    non_compliant_records: int
    
    # Integrity checks
    integrity_verified: bool
    integrity_errors: list[str] = Field(default_factory=list)
    
    # Sensitive data
    sensitive_data_accessed: int
    sensitive_data_modified: int
    sensitive_data_deleted: int
    
    # User activity
    active_users: int
    total_logins: int
    failed_logins: int
    
    # System changes
    policy_changes: int
    role_changes: int
    config_changes: int
    
    # Recommendations
    recommendations: list[str] = Field(default_factory=list)


class AuditStreamEvent(BaseModel):
    """Event for real-time audit stream."""
    id: UUID
    timestamp: datetime
    event_type: AuditEventType
    actor_id: Optional[str]
    target_id: Optional[str]
    action: AuditActionType
    severity: AuditSeverity
    description: Optional[str]


class SensitiveFieldMask(BaseModel):
    """Definition of sensitive fields to mask in audit logs."""
    field_name: str
    field_type: str  # password, api_key, ssn, credit_card, etc.
    mask_pattern: str  # How to mask (e.g., "****", "***-****")
    
    # When to mask
    always_mask: bool = True
    mask_in_logs: bool = True
    mask_in_exports: bool = True
    
    # Who can view unmasked
    unmasked_roles: list[str] = Field(default_factory=list)


class AuditArchive(BaseModel):
    """Archive information for audit records."""
    archive_id: UUID
    org_id: UUID
    
    # Archive details
    record_count: int
    date_range_start: datetime
    date_range_end: datetime
    
    # Storage
    archive_location: str
    archive_size_bytes: int
    checksum: str  # SHA-256
    
    # Retrieval
    retrieved_at: Optional[datetime] = None
    retrieval_count: int = 0
    
    # Lifecycle
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_permanent: bool = False


class AuditRetention(BaseModel):
    """Retention policy for audit logs."""
    org_id: UUID
    
    # Standard retention
    standard_retention_days: int = 90
    
    # Compliance retention (regulatory)
    compliance_retention_days: int = 365
    
    # Financial/sensitive retention
    financial_retention_days: int = 2555  # 7 years
    
    # Auto-archival
    auto_archive_after_days: int = 180
    archive_location: str = "s3://trustplane-archive"
    
    # Deletion policy
    auto_delete_after_days: Optional[int] = None
    require_approval_for_deletion: bool = True
    
    # Created/updated
    created_at: datetime
    updated_at: datetime


class AuditIntegrityCheck(BaseModel):
    """Integrity check result for audit trail."""
    check_id: UUID
    org_id: UUID
    
    # Check details
    start_record_id: UUID
    end_record_id: UUID
    record_count: int
    
    # Results
    is_valid: bool
    missing_records: list[UUID] = Field(default_factory=list)
    hash_mismatches: list[UUID] = Field(default_factory=list)
    chain_breaks: list[dict[str, Any]] = Field(default_factory=list)
    
    # Performance
    check_duration_ms: float
    checked_at: datetime


class AnomalyDetection(BaseModel):
    """Detected anomalies in audit trail."""
    anomaly_id: UUID
    org_id: UUID
    
    # What was detected
    anomaly_type: str  # "unusual_access", "privilege_escalation", "mass_export", etc.
    severity: AuditSeverity
    
    # Details
    description: str
    related_events: list[UUID]
    affected_users: list[str]
    affected_resources: list[str]
    
    # Context
    detected_at: datetime
    context: dict[str, Any]
    
    # Response
    is_reviewed: bool = False
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    response_action: Optional[str] = None
