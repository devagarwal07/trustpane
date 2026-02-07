"""
Tests for Dashboard Service and API
"""
import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from app.models.dashboard import (
    DashboardOverview, SLAMetrics, WorkflowStats, AgentPerformance,
    TimeRange, MetricTrend
)


def test_dashboard_models():
    """Test dashboard model instantiation"""
    # Overview
    overview = DashboardOverview(
        total_workflows=100,
        active_workflows=25,
        sla_compliance_rate=95.5
    )
    assert overview.total_workflows == 100
    assert overview.active_workflows == 25
    assert overview.sla_compliance_rate == 95.5
    
    # SLA Metrics
    sla_metrics = SLAMetrics(
        time_range=TimeRange.LAST_24_HOURS,
        total_slas=50,
        compliance_rate=92.0
    )
    assert sla_metrics.time_range == TimeRange.LAST_24_HOURS
    assert sla_metrics.compliance_rate == 92.0
    
    # Workflow Stats
    workflow_stats = WorkflowStats(
        time_range=TimeRange.LAST_7_DAYS,
        total_workflows=150,
        throughput_per_day=21.4
    )
    assert workflow_stats.total_workflows == 150
    assert workflow_stats.throughput_per_day == 21.4
    
    # Agent Performance
    agent_perf = AgentPerformance(
        time_range=TimeRange.LAST_7_DAYS,
        total_decisions=75,
        acceptance_rate=88.5
    )
    assert agent_perf.total_decisions == 75
    assert agent_perf.acceptance_rate == 88.5


def test_time_range_enum():
    """Test TimeRange enum values"""
    assert TimeRange.LAST_HOUR == "last_hour"
    assert TimeRange.LAST_24_HOURS == "last_24_hours"
    assert TimeRange.LAST_7_DAYS == "last_7_days"
    assert TimeRange.LAST_30_DAYS == "last_30_days"
    assert TimeRange.LAST_90_DAYS == "last_90_days"


def test_metric_trend_enum():
    """Test MetricTrend enum values"""
    assert MetricTrend.UP == "up"
    assert MetricTrend.DOWN == "down"
    assert MetricTrend.STABLE == "stable"


def test_dashboard_overview_defaults():
    """Test dashboard overview default values"""
    overview = DashboardOverview()
    assert overview.total_workflows == 0
    assert overview.active_workflows == 0
    assert overview.sla_compliance_rate == 0.0
    assert overview.unread_notifications == 0
    assert overview.agent_decisions_today == 0
    assert overview.avg_workflow_completion_hours is None


def test_sla_metrics_with_trends():
    """Test SLA metrics with trend indicators"""
    metrics = SLAMetrics(
        time_range=TimeRange.LAST_24_HOURS,
        total_slas=100,
        met_slas=92,
        soft_breaches=5,
        hard_breaches=3,
        compliance_rate=92.0,
        compliance_trend=MetricTrend.UP,
        breach_trend=MetricTrend.DOWN
    )
    
    assert metrics.met_slas == 92
    assert metrics.soft_breaches == 5
    assert metrics.hard_breaches == 3
    assert metrics.compliance_trend == MetricTrend.UP
    assert metrics.breach_trend == MetricTrend.DOWN


def test_workflow_stats_with_breakdown():
    """Test workflow stats with status breakdown"""
    stats = WorkflowStats(
        time_range=TimeRange.LAST_7_DAYS,
        total_workflows=200,
        by_status={
            "active": 50,
            "completed": 120,
            "failed": 10,
            "paused": 20
        },
        by_type={
            "support_ticket": 80,
            "incident": 60,
            "change_request": 40,
            "approval": 20
        }
    )
    
    assert stats.total_workflows == 200
    assert stats.by_status["active"] == 50
    assert stats.by_status["completed"] == 120
    assert stats.by_type["support_ticket"] == 80


def test_agent_performance_metrics():
    """Test agent performance with decision breakdown"""
    perf = AgentPerformance(
        time_range=TimeRange.LAST_7_DAYS,
        total_decisions=150,
        decisions_accepted=120,
        decisions_rejected=30,
        acceptance_rate=80.0,
        workflows_influenced=75,
        by_decision_type={
            "escalate": 40,
            "assign": 50,
            "prioritize": 35,
            "recommend": 25
        }
    )
    
    assert perf.total_decisions == 150
    assert perf.acceptance_rate == 80.0
    assert perf.workflows_influenced == 75
    assert perf.by_decision_type["escalate"] == 40


def test_dashboard_timestamp_generation():
    """Test that timestamps are auto-generated"""
    overview = DashboardOverview()
    assert overview.timestamp is not None
    assert isinstance(overview.timestamp, datetime)
    
    # Timestamp should be recent (within last minute)
    now = datetime.utcnow()
    time_diff = (now - overview.timestamp).total_seconds()
    assert time_diff < 60  # Less than 1 minute old
