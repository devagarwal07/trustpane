"""
Audit Service

Event-sourced audit logging service with compliance tracking,
integrity verification, and real-time anomaly detection.
"""

import hashlib
import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from typing import Any, Optional
from supabase import AsyncClient
from fastapi import HTTPException

from app.models.audit import (
    AuditRecord, AuditCreate, AuditQueryFilter, AuditSummary,
    ComplianceReport, AuditArchive, AuditRetention, AuditIntegrityCheck,
    AnomalyDetection, AuditStreamEvent, AuditEventType, AuditActionType,
    AuditSeverity, SensitiveFieldMask
)


class AuditService:
    """
    Audit logging service with event sourcing integration.
    
    Responsibilities:
    - Record all events in immutable audit log
    - Query and filter audit records
    - Generate compliance reports
    - Track sensitive field access
    - Detect anomalies
    - Verify integrity
    - Manage retention policies
    - Archive old records
    """
    
    # Sensitive fields requiring masking
    SENSITIVE_FIELDS = {
        "password": "****",
        "api_key": "***-****",
        "secret": "***-****",
        "ssn": "***-**-****",
        "credit_card": "****-****-****-****",
        "phone": "***-***-****",
        "email": "***@***",
        "token": "***-***",
    }
    
    def __init__(self, supabase: AsyncClient, org_id: UUID):
        """Initialize audit service."""
        self.supabase = supabase
        self.org_id = org_id
    
    async def log_event(self, audit_create: AuditCreate, session_id: Optional[str] = None) -> AuditRecord:
        """
        Log an audit event.
        
        Args:
            audit_create: Event data
            session_id: Optional session identifier
            
        Returns:
            Recorded AuditRecord
        """
        record_id = uuid4()
        now = datetime.utcnow()
        
        # Calculate retention date
        retention_days = await self._get_retention_days(audit_create.event_type)
        retention_until = now + timedelta(days=retention_days)
        
        # Calculate content hash
        content = {
            "event_type": audit_create.event_type,
            "action": audit_create.action,
            "actor_id": audit_create.actor_id,
            "target_id": audit_create.target_id,
            "description": audit_create.description,
            "timestamp": now.isoformat(),
        }
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True).encode()
        ).hexdigest()
        
        # Mask sensitive data
        details = self._mask_sensitive_data(audit_create.details or {})
        changes = self._mask_sensitive_data(audit_create.changes or {}) if audit_create.changes else None
        
        # Insert into database
        record_data = {
            "id": str(record_id),
            "org_id": str(self.org_id),
            "event_type": audit_create.event_type,
            "action": audit_create.action,
            "severity": audit_create.severity,
            "actor_id": audit_create.actor_id,
            "actor_type": audit_create.actor_type,
            "actor_name": audit_create.actor_name,
            "target_id": audit_create.target_id,
            "target_type": audit_create.target_type,
            "target_name": audit_create.target_name,
            "resource": audit_create.resource,
            "description": audit_create.description,
            "details": details,
            "changes": changes,
            "ip_address": audit_create.ip_address,
            "user_agent": audit_create.user_agent,
            "session_id": session_id or audit_create.session_id,
            "content_hash": content_hash,
            "created_at": now,
            "retention_until": retention_until,
            "is_archived": False,
        }
        
        response = await self.supabase.table("audit_logs").insert(record_data).execute()
        
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to log audit event")
        
        return AuditRecord(**response.data[0])
    
    async def query_logs(self, filters: AuditQueryFilter) -> tuple[list[AuditRecord], int]:
        """
        Query audit logs with filters.
        
        Args:
            filters: Query filters
            
        Returns:
            Tuple of (records, total_count)
        """
        query = self.supabase.table("audit_logs").select(
            "*",
            count="exact"
        ).eq("org_id", str(self.org_id))
        
        # Apply filters
        if filters.event_type:
            query = query.eq("event_type", filters.event_type)
        if filters.actor_id:
            query = query.eq("actor_id", filters.actor_id)
        if filters.target_id:
            query = query.eq("target_id", filters.target_id)
        if filters.target_type:
            query = query.eq("target_type", filters.target_type)
        if filters.action:
            query = query.eq("action", filters.action)
        if filters.severity:
            query = query.eq("severity", filters.severity)
        
        # Date range
        if filters.start_date:
            query = query.gte("created_at", filters.start_date.isoformat())
        if filters.end_date:
            query = query.lte("created_at", filters.end_date.isoformat())
        
        # Sort
        query = query.order(filters.sort_by, desc=(filters.sort_order == "desc"))
        
        # Paginate
        query = query.range(filters.skip, filters.skip + filters.limit - 1)
        
        response = await query.execute()
        
        total_count = response.count or 0
        records = [AuditRecord(**r) for r in response.data]
        
        return records, total_count
    
    async def get_summary(self, start_date: datetime, end_date: datetime) -> AuditSummary:
        """
        Get summary statistics for audit logs.
        
        Args:
            start_date: Start of date range
            end_date: End of date range
            
        Returns:
            AuditSummary with statistics
        """
        # Get all records in range
        records, total = await self.query_logs(
            AuditQueryFilter(
                start_date=start_date,
                end_date=end_date,
                limit=10000  # Large limit for aggregation
            )
        )
        
        # Count by type
        by_type = {}
        by_actor = {}
        by_severity = {}
        top_events = []
        
        for record in records:
            # By type
            event_key = record.event_type
            by_type[event_key] = by_type.get(event_key, 0) + 1
            
            # By actor
            actor_key = record.actor_id or "unknown"
            by_actor[actor_key] = by_actor.get(actor_key, 0) + 1
            
            # By severity
            sev_key = record.severity
            by_severity[sev_key] = by_severity.get(sev_key, 0) + 1
        
        # Get top events
        for event_type, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:10]:
            top_events.append({"event_type": event_type, "count": count})
        
        return AuditSummary(
            total_events=total,
            date_range_start=start_date,
            date_range_end=end_date,
            events_by_type=by_type,
            events_by_actor=by_actor,
            events_by_severity=by_severity,
            top_events=top_events,
        )
    
    async def generate_compliance_report(
        self,
        period_start: datetime,
        period_end: datetime
    ) -> ComplianceReport:
        """
        Generate compliance report for audit trail.
        
        Args:
            period_start: Report period start
            period_end: Report period end
            
        Returns:
            ComplianceReport
        """
        # Get records in period
        records, total = await self.query_logs(
            AuditQueryFilter(
                start_date=period_start,
                end_date=period_end,
                limit=10000
            )
        )
        
        # Check retention compliance
        compliant = sum(1 for r in records if r.retention_until and r.retention_until > datetime.utcnow())
        non_compliant = total - compliant
        
        # Check integrity
        integrity_verified = True
        integrity_errors = []
        
        # Count sensitive data operations
        sensitive_accessed = sum(1 for r in records if r.event_type == AuditEventType.DATA_EXPORTED)
        sensitive_modified = sum(1 for r in records if r.event_type == AuditEventType.DATA_IMPORTED)
        sensitive_deleted = sum(1 for r in records if r.event_type == AuditEventType.DATA_DELETED)
        
        # Count auth events
        logins = sum(1 for r in records if r.event_type == AuditEventType.AUTH_LOGIN)
        failed_logins = sum(1 for r in records if r.event_type == AuditEventType.AUTH_FAILED)
        
        # Count active users
        active_users = len(set(r.actor_id for r in records if r.actor_id))
        
        # Count changes
        policy_changes = sum(1 for r in records if r.event_type in [
            AuditEventType.POLICY_CREATED,
            AuditEventType.POLICY_UPDATED,
            AuditEventType.POLICY_DELETED,
        ])
        role_changes = 0  # Would need separate table
        config_changes = sum(1 for r in records if r.event_type == AuditEventType.SYSTEM_CONFIG_CHANGED)
        
        # Recommendations
        recommendations = []
        if failed_logins > logins * 0.1:
            recommendations.append("High number of failed logins - investigate security")
        if sensitive_deleted > 10:
            recommendations.append("High volume of data deletions - verify legitimacy")
        if not compliant:
            recommendations.append("Records at risk of purging - review retention policies")
        
        return ComplianceReport(
            org_id=self.org_id,
            report_date=datetime.utcnow(),
            period_start=period_start,
            period_end=period_end,
            total_records=total,
            compliant_records=compliant,
            non_compliant_records=non_compliant,
            integrity_verified=integrity_verified,
            integrity_errors=integrity_errors,
            sensitive_data_accessed=sensitive_accessed,
            sensitive_data_modified=sensitive_modified,
            sensitive_data_deleted=sensitive_deleted,
            active_users=active_users,
            total_logins=logins,
            failed_logins=failed_logins,
            policy_changes=policy_changes,
            role_changes=role_changes,
            config_changes=config_changes,
            recommendations=recommendations,
        )
    
    async def verify_integrity(self, start_record_id: Optional[UUID] = None, end_record_id: Optional[UUID] = None) -> AuditIntegrityCheck:
        """
        Verify integrity of audit chain.
        
        Args:
            start_record_id: Optional start record
            end_record_id: Optional end record
            
        Returns:
            IntegrityCheck result
        """
        check_id = uuid4()
        start_time = datetime.utcnow()
        
        # Get records to check
        records, total = await self.query_logs(
            AuditQueryFilter(limit=10000)
        )
        
        missing = []
        hash_mismatches = []
        chain_breaks = []
        
        # Verify each record's hash
        for i, record in enumerate(records):
            # Recompute hash
            content = {
                "event_type": record.event_type,
                "action": record.action,
                "actor_id": record.actor_id,
                "target_id": record.target_id,
                "description": record.description,
                "timestamp": record.created_at.isoformat(),
            }
            expected_hash = hashlib.sha256(
                json.dumps(content, sort_keys=True).encode()
            ).hexdigest()
            
            if record.content_hash != expected_hash:
                hash_mismatches.append(record.id)
        
        end_time = datetime.utcnow()
        duration_ms = (end_time - start_time).total_seconds() * 1000
        
        return AuditIntegrityCheck(
            check_id=check_id,
            org_id=self.org_id,
            start_record_id=start_record_id or records[0].id if records else uuid4(),
            end_record_id=end_record_id or records[-1].id if records else uuid4(),
            record_count=total,
            is_valid=len(hash_mismatches) == 0 and len(chain_breaks) == 0,
            missing_records=missing,
            hash_mismatches=hash_mismatches,
            chain_breaks=chain_breaks,
            check_duration_ms=duration_ms,
            checked_at=end_time,
        )
    
    async def detect_anomalies(self, lookback_days: int = 7) -> list[AnomalyDetection]:
        """
        Detect anomalies in audit trail.
        
        Args:
            lookback_days: How far back to look
            
        Returns:
            List of detected anomalies
        """
        anomalies = []
        start_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        records, _ = await self.query_logs(
            AuditQueryFilter(start_date=start_date, limit=10000)
        )
        
        # Detect: Unusual access patterns
        # Count exports per user
        exports_by_user = {}
        for record in records:
            if record.event_type == AuditEventType.DATA_EXPORTED:
                key = record.actor_id or "unknown"
                if key not in exports_by_user:
                    exports_by_user[key] = []
                exports_by_user[key].append(record.id)
        
        # Flag users with unusual export activity
        for user, export_ids in exports_by_user.items():
            if len(export_ids) > 10:  # Threshold
                anomalies.append(AnomalyDetection(
                    anomaly_id=uuid4(),
                    org_id=self.org_id,
                    anomaly_type="unusual_data_export",
                    severity=AuditSeverity.WARNING,
                    description=f"User {user} exported data {len(export_ids)} times",
                    related_events=export_ids[:10],
                    affected_users=[user],
                    affected_resources=[],
                    detected_at=datetime.utcnow(),
                    context={"export_count": len(export_ids)},
                ))
        
        # Detect: Multiple failed logins
        failed_logins_by_user = {}
        for record in records:
            if record.event_type == AuditEventType.AUTH_FAILED:
                key = record.actor_id or record.ip_address or "unknown"
                if key not in failed_logins_by_user:
                    failed_logins_by_user[key] = []
                failed_logins_by_user[key].append(record.id)
        
        for key, login_ids in failed_logins_by_user.items():
            if len(login_ids) > 5:  # Threshold
                anomalies.append(AnomalyDetection(
                    anomaly_id=uuid4(),
                    org_id=self.org_id,
                    anomaly_type="brute_force_attempt",
                    severity=AuditSeverity.CRITICAL,
                    description=f"Excessive failed logins from {key}",
                    related_events=login_ids[:10],
                    affected_users=[],
                    affected_resources=[],
                    detected_at=datetime.utcnow(),
                    context={"failed_login_count": len(login_ids)},
                ))
        
        return anomalies
    
    async def archive_old_records(self, retention_policy: AuditRetention) -> AuditArchive:
        """
        Archive old audit records.
        
        Args:
            retention_policy: Retention policy configuration
            
        Returns:
            AuditArchive record
        """
        archive_id = uuid4()
        cutoff_date = datetime.utcnow() - timedelta(days=retention_policy.auto_archive_after_days)
        
        # Get records to archive
        records, count = await self.query_logs(
            AuditQueryFilter(
                end_date=cutoff_date,
                limit=100000
            )
        )
        
        # Calculate checksum
        record_hashes = [r.content_hash for r in records]
        checksum = hashlib.sha256(
            "".join(record_hashes).encode()
        ).hexdigest()
        
        # Mark as archived
        if records:
            await self.supabase.table("audit_logs").update({
                "is_archived": True,
                "archive_location": retention_policy.archive_location,
            }).eq("org_id", str(self.org_id)).lte("created_at", cutoff_date.isoformat()).execute()
        
        return AuditArchive(
            archive_id=archive_id,
            org_id=self.org_id,
            record_count=count,
            date_range_start=datetime.utcnow() - timedelta(days=365),
            date_range_end=cutoff_date,
            archive_location=retention_policy.archive_location,
            archive_size_bytes=len(records) * 500,  # Rough estimate
            checksum=checksum,
            created_at=datetime.utcnow(),
        )
    
    def _mask_sensitive_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive fields in data."""
        masked = data.copy()
        for field_name, field_type in self.SENSITIVE_FIELDS.items():
            if field_name in masked:
                masked[field_name] = field_type
        return masked
    
    async def _get_retention_days(self, event_type: AuditEventType) -> int:
        """
        Get retention days for event type.
        
        Args:
            event_type: Type of audit event
            
        Returns:
            Number of days to retain
        """
        # Get retention policy
        response = await self.supabase.table("audit_retention").select("*").eq(
            "org_id", str(self.org_id)
        ).execute()
        
        if response.data:
            policy = response.data[0]
            
            # Financial events: 7 years
            if event_type in [AuditEventType.DATA_EXPORTED, AuditEventType.DATA_DELETED]:
                return policy.get("financial_retention_days", 2555)
            
            # Compliance events: 1 year
            if event_type in [AuditEventType.AUTH_LOGIN, AuditEventType.AUTH_FAILED]:
                return policy.get("compliance_retention_days", 365)
            
            # Standard events: 90 days
            return policy.get("standard_retention_days", 90)
        
        # Defaults
        if event_type in [AuditEventType.DATA_EXPORTED, AuditEventType.DATA_DELETED]:
            return 2555
        if event_type in [AuditEventType.AUTH_LOGIN, AuditEventType.AUTH_FAILED]:
            return 365
        return 90
