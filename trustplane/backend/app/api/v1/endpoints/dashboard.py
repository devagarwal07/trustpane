"""
Dashboard API endpoints

Provides aggregated metrics and system health data.
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import TenantContext, get_tenant_context
from app.models.dashboard import (
    DashboardOverview, SLAMetrics, WorkflowStats, AgentPerformance,
    TimeRange, TimeSeriesMetric
)
from app.services.dashboard_service import get_dashboard_service, DashboardService
from app.services.workflow_service import get_workflow_service
from app.services.sla_service import get_sla_service
from app.services.notification_service import get_notification_service

router = APIRouter()


def _get_dashboard_service(ctx: TenantContext = Depends(get_tenant_context)) -> DashboardService:
    """Get dashboard service with all dependencies."""
    workflow_service = get_workflow_service(ctx.org_id)
    sla_service = get_sla_service(ctx.org_id)
    notification_service = get_notification_service(ctx.org_id)
    
    return get_dashboard_service(
        ctx.org_id,
        workflow_service,
        sla_service,
        notification_service
    )


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    dashboard: DashboardService = Depends(_get_dashboard_service)
) -> DashboardOverview:
    """
    Get overall system health and key metrics.
    
    Returns:
    - Workflow counts (total, active, completed, failed)
    - SLA metrics (compliance rate, breaches)
    - Notification counts (unread, critical)
    - Agent activity (decisions today)
    - Average completion time
    """
    return await dashboard.get_overview()


@router.get("/sla-metrics", response_model=SLAMetrics)
async def get_sla_metrics(
    time_range: TimeRange = Query(TimeRange.LAST_24_HOURS, description="Time range for metrics"),
    dashboard: DashboardService = Depends(_get_dashboard_service)
) -> SLAMetrics:
    """
    Get SLA-specific metrics and compliance data.
    
    Returns:
    - Compliance rate
    - Breach counts (soft/hard)
    - Response and resolution times
    - Breakdown by priority and type
    - Trends
    """
    return await dashboard.get_sla_metrics(time_range)


@router.get("/workflow-stats", response_model=WorkflowStats)
async def get_workflow_stats(
    time_range: TimeRange = Query(TimeRange.LAST_7_DAYS, description="Time range for stats"),
    dashboard: DashboardService = Depends(_get_dashboard_service)
) -> WorkflowStats:
    """
    Get workflow statistics and performance data.
    
    Returns:
    - Volume metrics (created, completed, failed)
    - Status and type breakdowns
    - Completion times (average, median)
    - Throughput and trends
    - Bottlenecks (awaiting assignment, escalated)
    """
    return await dashboard.get_workflow_stats(time_range)


@router.get("/agent-performance", response_model=AgentPerformance)
async def get_agent_performance(
    time_range: TimeRange = Query(TimeRange.LAST_7_DAYS, description="Time range for performance"),
    dashboard: DashboardService = Depends(_get_dashboard_service)
) -> AgentPerformance:
    """
    Get agent performance metrics and effectiveness data.
    
    Returns:
    - Decision counts (total, accepted, rejected)
    - Acceptance rate
    - Workflows influenced
    - Decision timing
    - Quality score
    - Activity trends
    """
    return await dashboard.get_agent_performance(time_range)


@router.get("/time-series/{metric_name}", response_model=TimeSeriesMetric)
async def get_time_series(
    metric_name: str,
    time_range: TimeRange = Query(TimeRange.LAST_24_HOURS, description="Time range for series"),
    dashboard: DashboardService = Depends(_get_dashboard_service)
) -> TimeSeriesMetric:
    """
    Get time series data for a specific metric.
    
    Supported metrics:
    - workflow_volume: Number of workflows created over time
    - sla_breaches: Number of SLA breaches over time
    - agent_decisions: Number of agent decisions over time
    
    Returns time-bucketed data points for charting.
    """
    return await dashboard.get_time_series(metric_name, time_range)
