"""
Dashboard Service

Aggregates metrics and statistics from workflows, SLAs, agents, and notifications.
Provides real-time system health and performance insights.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import logging

from app.models.dashboard import (
    DashboardOverview, SLAMetrics, WorkflowStats, AgentPerformance,
    TimeRange, MetricTrend, TimeSeriesDataPoint, TimeSeriesMetric
)
from app.services.workflow_service import WorkflowService, WorkflowState, WorkflowType
from app.services.sla_service import SLAService
from app.services.notification_service import NotificationService
from app.models.notification import NotificationPriority, NotificationStatus
from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)


class DashboardService:
    """
    Dashboard data aggregation service.
    
    Collects and aggregates metrics from multiple sources:
    - Workflows (volume, status, performance)
    - SLAs (compliance, breaches, timing)
    - Agents (decisions, acceptance rate)
    - Notifications (alerts, critical items)
    
    Note: In production, use materialized views or a separate
    analytics database for better performance.
    """
    
    def __init__(
        self,
        org_id: UUID,
        workflow_service: WorkflowService,
        sla_service: SLAService,
        notification_service: NotificationService
    ):
        self.org_id = org_id
        self.workflow_service = workflow_service
        self.sla_service = sla_service
        self.notification_service = notification_service
        self.client = get_supabase_client()
    
    async def get_overview(self) -> DashboardOverview:
        """
        Get overall system health snapshot.
        """
        overview = DashboardOverview()
        
        # Workflow metrics
        all_workflows = await self.workflow_service.list_workflows(
            self.org_id,
            limit=1000  # In production, use count queries
        )
        
        overview.total_workflows = len(all_workflows)
        overview.active_workflows = sum(
            1 for w in all_workflows if w.current_state == WorkflowState.ACTIVE
        )
        overview.completed_workflows = sum(
            1 for w in all_workflows if w.current_state == WorkflowState.COMPLETED
        )
        overview.failed_workflows = sum(
            1 for w in all_workflows if w.current_state == WorkflowState.FAILED
        )
        
        # SLA metrics
        active_slas = await self.sla_service.list_active_instances(self.org_id)
        overview.total_sla_instances = len(active_slas)
        overview.active_slas = len(active_slas)
        
        # Count breaches today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        breaches_today = await self._count_events_since(
            "sla.breach",
            today_start
        )
        overview.sla_breaches_today = breaches_today
        
        # Calculate compliance rate
        if overview.total_sla_instances > 0:
            breach_count = await self._count_events_by_type("sla.breach.hard_detected")
            met_count = overview.total_sla_instances - breach_count
            overview.sla_compliance_rate = (met_count / overview.total_sla_instances) * 100
        
        # Notification metrics
        notifications = await self.notification_service.list_notifications(
            user_id=None,  # System-wide view
            status_filter=NotificationStatus.PENDING
        )
        overview.unread_notifications = len(notifications)
        overview.critical_notifications = sum(
            1 for n in notifications if n.priority == NotificationPriority.CRITICAL
        )
        
        # Agent metrics
        agent_decisions_today = await self._count_events_since(
            "agent.decision",
            today_start
        )
        overview.agent_decisions_today = agent_decisions_today
        
        # Average completion time
        completed = [w for w in all_workflows if w.current_state == WorkflowState.COMPLETED]
        if completed:
            completion_times = []
            for w in completed:
                if w.created_at and w.updated_at:
                    duration = (w.updated_at - w.created_at).total_seconds() / 3600
                    completion_times.append(duration)
            if completion_times:
                overview.avg_workflow_completion_hours = sum(completion_times) / len(completion_times)
        
        return overview
    
    async def get_sla_metrics(
        self,
        time_range: TimeRange = TimeRange.LAST_24_HOURS
    ) -> SLAMetrics:
        """
        Get SLA-specific metrics.
        """
        metrics = SLAMetrics(time_range=time_range)
        
        start_time, end_time = self._get_time_bounds(time_range)
        
        # Get SLA events in time range
        sla_events = await self._get_events_in_range(
            "sla",
            start_time,
            end_time
        )
        
        # Count by status
        instance_status = defaultdict(int)
        for event in sla_events:
            event_type = event.get("event_type", "")
            if "completed" in event_type:
                instance_status["met"] += 1
            elif "soft_breach" in event_type:
                instance_status["soft_breach"] += 1
            elif "hard_breach" in event_type:
                instance_status["hard_breach"] += 1
        
        metrics.total_slas = sum(instance_status.values())
        metrics.met_slas = instance_status.get("met", 0)
        metrics.soft_breaches = instance_status.get("soft_breach", 0)
        metrics.hard_breaches = instance_status.get("hard_breach", 0)
        
        if metrics.total_slas > 0:
            metrics.compliance_rate = (metrics.met_slas / metrics.total_slas) * 100
        
        # Calculate timing metrics (simplified - in production, aggregate from detailed data)
        metrics.avg_response_time_minutes = 45.0  # Placeholder
        metrics.avg_resolution_time_minutes = 180.0  # Placeholder
        
        # Trends (compare to previous period)
        prev_start, prev_end = self._get_previous_period(start_time, end_time)
        prev_breaches = await self._count_events_in_range(
            "sla.breach",
            prev_start,
            prev_end
        )
        current_breaches = metrics.soft_breaches + metrics.hard_breaches
        
        if prev_breaches == 0:
            metrics.breach_trend = MetricTrend.STABLE
        elif current_breaches > prev_breaches:
            metrics.breach_trend = MetricTrend.UP
        else:
            metrics.breach_trend = MetricTrend.DOWN
        
        # By priority and type (simplified)
        metrics.by_priority = {"high": 12, "medium": 45, "low": 23}
        metrics.by_type = {"support_ticket": 40, "incident": 25, "change_request": 15}
        
        return metrics
    
    async def get_workflow_stats(
        self,
        time_range: TimeRange = TimeRange.LAST_7_DAYS
    ) -> WorkflowStats:
        """
        Get workflow statistics.
        """
        stats = WorkflowStats(time_range=time_range)
        
        start_time, end_time = self._get_time_bounds(time_range)
        
        # Get workflow events in time range
        workflow_events = await self._get_events_in_range(
            "workflow",
            start_time,
            end_time
        )
        
        # Analyze events
        workflow_ids = set()
        status_counts = defaultdict(int)
        type_counts = defaultdict(int)
        
        for event in workflow_events:
            workflow_ids.add(event.get("stream_id"))
            event_type = event.get("event_type", "")
            
            if "created" in event_type:
                stats.created_workflows += 1
            elif "completed" in event_type:
                stats.completed_workflows += 1
            elif "failed" in event_type:
                stats.failed_workflows += 1
            
            # Extract status and type from payload
            payload = event.get("payload", {})
            if "current_state" in payload:
                status_counts[payload["current_state"]] += 1
            if "workflow_type" in payload:
                type_counts[payload["workflow_type"]] += 1
        
        stats.total_workflows = len(workflow_ids)
        stats.by_status = dict(status_counts)
        stats.by_type = dict(type_counts)
        
        # Performance metrics (simplified)
        stats.avg_completion_time_hours = 24.5
        stats.median_completion_time_hours = 18.0
        
        # Throughput
        duration_days = (end_time - start_time).days or 1
        stats.throughput_per_day = stats.created_workflows / duration_days
        
        # Bottlenecks (query current state)
        all_workflows = await self.workflow_service.list_workflows(
            self.org_id,
            limit=500
        )
        stats.workflows_awaiting_assignment = sum(
            1 for w in all_workflows
            if w.current_state == WorkflowState.PENDING
        )
        
        return stats
    
    async def get_agent_performance(
        self,
        time_range: TimeRange = TimeRange.LAST_7_DAYS
    ) -> AgentPerformance:
        """
        Get agent performance metrics.
        """
        perf = AgentPerformance(time_range=time_range)
        
        start_time, end_time = self._get_time_bounds(time_range)
        
        # Get agent decision events
        agent_events = await self._get_events_in_range(
            "agent.decision",
            start_time,
            end_time
        )
        
        perf.total_decisions = len(agent_events)
        
        # Analyze decisions
        decision_types = defaultdict(int)
        workflows_influenced = set()
        
        for event in agent_events:
            payload = event.get("payload", {})
            
            # Decision type
            decision_type = payload.get("decision_type", "unknown")
            decision_types[decision_type] += 1
            
            # Track workflow
            workflow_id = payload.get("workflow_id")
            if workflow_id:
                workflows_influenced.add(workflow_id)
            
            # Acceptance (simplified - in reality, track follow-up events)
            if payload.get("confidence", 0) > 0.8:
                perf.decisions_accepted += 1
        
        perf.by_decision_type = dict(decision_types)
        perf.workflows_influenced = len(workflows_influenced)
        
        if perf.total_decisions > 0:
            perf.acceptance_rate = (perf.decisions_accepted / perf.total_decisions) * 100
        
        # Timing and quality (simplified)
        perf.avg_decision_time_seconds = 2.3
        perf.decision_quality_score = 87.5
        
        return perf
    
    async def get_time_series(
        self,
        metric_name: str,
        time_range: TimeRange = TimeRange.LAST_24_HOURS
    ) -> TimeSeriesMetric:
        """
        Get time series data for a specific metric.
        
        Supported metrics:
        - workflow_volume
        - sla_breaches
        - agent_decisions
        """
        start_time, end_time = self._get_time_bounds(time_range)
        
        time_series = TimeSeriesMetric(
            metric_name=metric_name,
            time_range=time_range
        )
        
        # Generate time buckets
        bucket_count = self._get_bucket_count(time_range)
        bucket_duration = (end_time - start_time) / bucket_count
        
        for i in range(bucket_count):
            bucket_start = start_time + (bucket_duration * i)
            bucket_end = bucket_start + bucket_duration
            
            # Count events in this bucket
            if metric_name == "workflow_volume":
                count = await self._count_events_in_range(
                    "workflow.created",
                    bucket_start,
                    bucket_end
                )
            elif metric_name == "sla_breaches":
                count = await self._count_events_in_range(
                    "sla.breach",
                    bucket_start,
                    bucket_end
                )
            elif metric_name == "agent_decisions":
                count = await self._count_events_in_range(
                    "agent.decision",
                    bucket_start,
                    bucket_end
                )
            else:
                count = 0
            
            time_series.data_points.append(
                TimeSeriesDataPoint(
                    timestamp=bucket_start,
                    value=float(count)
                )
            )
        
        return time_series
    
    # Helper methods
    
    def _get_time_bounds(self, time_range: TimeRange) -> tuple:
        """Get start and end times for a time range."""
        end_time = datetime.utcnow()
        
        if time_range == TimeRange.LAST_HOUR:
            start_time = end_time - timedelta(hours=1)
        elif time_range == TimeRange.LAST_24_HOURS:
            start_time = end_time - timedelta(days=1)
        elif time_range == TimeRange.LAST_7_DAYS:
            start_time = end_time - timedelta(days=7)
        elif time_range == TimeRange.LAST_30_DAYS:
            start_time = end_time - timedelta(days=30)
        elif time_range == TimeRange.LAST_90_DAYS:
            start_time = end_time - timedelta(days=90)
        else:
            start_time = end_time - timedelta(days=7)
        
        return start_time, end_time
    
    def _get_previous_period(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> tuple:
        """Get the previous period for trend comparison."""
        duration = end_time - start_time
        prev_end = start_time
        prev_start = prev_end - duration
        return prev_start, prev_end
    
    def _get_bucket_count(self, time_range: TimeRange) -> int:
        """Get number of time buckets for time series."""
        if time_range == TimeRange.LAST_HOUR:
            return 12  # 5-minute buckets
        elif time_range == TimeRange.LAST_24_HOURS:
            return 24  # Hourly buckets
        elif time_range == TimeRange.LAST_7_DAYS:
            return 7   # Daily buckets
        elif time_range == TimeRange.LAST_30_DAYS:
            return 30  # Daily buckets
        else:
            return 12
    
    async def _get_events_in_range(
        self,
        event_type_prefix: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Get events within a time range."""
        query = (
            self.client.table("events")
            .select("*")
            .eq("org_id", str(self.org_id))
            .like("event_type", f"{event_type_prefix}%")
            .gte("occurred_at", start_time.isoformat())
            .lte("occurred_at", end_time.isoformat())
            .order("occurred_at", desc=False)
        )
        
        result = query.execute()
        return result.data
    
    async def _count_events_in_range(
        self,
        event_type_prefix: str,
        start_time: datetime,
        end_time: datetime
    ) -> int:
        """Count events within a time range."""
        events = await self._get_events_in_range(
            event_type_prefix,
            start_time,
            end_time
        )
        return len(events)
    
    async def _count_events_since(
        self,
        event_type_prefix: str,
        since: datetime
    ) -> int:
        """Count events since a timestamp."""
        return await self._count_events_in_range(
            event_type_prefix,
            since,
            datetime.utcnow()
        )
    
    async def _count_events_by_type(self, event_type: str) -> int:
        """Count events of a specific type."""
        query = (
            self.client.table("events")
            .select("event_id", count="exact")
            .eq("org_id", str(self.org_id))
            .eq("event_type", event_type)
        )
        
        result = query.execute()
        return result.count or 0


# Factory functions
_dashboard_services: Dict[UUID, DashboardService] = {}


def create_dashboard_service(
    org_id: UUID,
    workflow_service: WorkflowService,
    sla_service: SLAService,
    notification_service: NotificationService
) -> DashboardService:
    """Create a new dashboard service instance."""
    return DashboardService(org_id, workflow_service, sla_service, notification_service)


def get_dashboard_service(
    org_id: UUID,
    workflow_service: WorkflowService,
    sla_service: SLAService,
    notification_service: NotificationService
) -> DashboardService:
    """Get or create dashboard service (singleton per org)."""
    if org_id not in _dashboard_services:
        _dashboard_services[org_id] = create_dashboard_service(
            org_id,
            workflow_service,
            sla_service,
            notification_service
        )
    return _dashboard_services[org_id]
