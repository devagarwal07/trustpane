"""
Dashboard models

Data models for dashboard metrics and aggregations.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import Field
from uuid import UUID
from enum import Enum

from app.models.base import BaseModel


class TimeRange(str, Enum):
    """Time range for metrics"""
    LAST_HOUR = "last_hour"
    LAST_24_HOURS = "last_24_hours"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    CUSTOM = "custom"


class MetricTrend(str, Enum):
    """Trend direction"""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class DashboardOverview(BaseModel):
    """Overall system health and key metrics"""
    total_workflows: int = 0
    active_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    
    total_sla_instances: int = 0
    active_slas: int = 0
    sla_breaches_today: int = 0
    sla_compliance_rate: float = 0.0  # Percentage
    
    unread_notifications: int = 0
    critical_notifications: int = 0
    
    agent_decisions_today: int = 0
    avg_workflow_completion_hours: Optional[float] = None
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SLAMetrics(BaseModel):
    """SLA-specific metrics"""
    time_range: TimeRange
    
    # Compliance
    total_slas: int = 0
    met_slas: int = 0
    soft_breaches: int = 0
    hard_breaches: int = 0
    compliance_rate: float = 0.0
    
    # Timing
    avg_response_time_minutes: Optional[float] = None
    avg_resolution_time_minutes: Optional[float] = None
    
    # Trends
    compliance_trend: MetricTrend = MetricTrend.STABLE
    breach_trend: MetricTrend = MetricTrend.STABLE
    
    # By priority (high/medium/low)
    by_priority: Dict[str, int] = Field(default_factory=dict)
    
    # By type
    by_type: Dict[str, int] = Field(default_factory=dict)
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WorkflowStats(BaseModel):
    """Workflow statistics"""
    time_range: TimeRange
    
    # Volume
    total_workflows: int = 0
    created_workflows: int = 0
    completed_workflows: int = 0
    failed_workflows: int = 0
    
    # Status breakdown
    by_status: Dict[str, int] = Field(default_factory=dict)
    
    # By type
    by_type: Dict[str, int] = Field(default_factory=dict)
    
    # Performance
    avg_completion_time_hours: Optional[float] = None
    median_completion_time_hours: Optional[float] = None
    
    # Throughput
    throughput_per_day: float = 0.0
    throughput_trend: MetricTrend = MetricTrend.STABLE
    
    # Bottlenecks
    workflows_awaiting_assignment: int = 0
    workflows_escalated: int = 0
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentPerformance(BaseModel):
    """Agent performance metrics"""
    time_range: TimeRange
    
    # Activity
    total_decisions: int = 0
    decisions_accepted: int = 0
    decisions_rejected: int = 0
    acceptance_rate: float = 0.0
    
    # Impact
    workflows_influenced: int = 0
    avg_decision_time_seconds: Optional[float] = None
    
    # By decision type
    by_decision_type: Dict[str, int] = Field(default_factory=dict)
    
    # Quality
    decision_quality_score: Optional[float] = None  # 0-100
    
    # Trends
    activity_trend: MetricTrend = MetricTrend.STABLE
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TimeSeriesDataPoint(BaseModel):
    """Single data point in a time series"""
    timestamp: datetime
    value: float
    label: Optional[str] = None


class TimeSeriesMetric(BaseModel):
    """Time series data for charts"""
    metric_name: str
    time_range: TimeRange
    data_points: List[TimeSeriesDataPoint] = Field(default_factory=list)
    unit: Optional[str] = None
