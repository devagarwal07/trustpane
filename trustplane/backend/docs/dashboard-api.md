# Dashboard API

The Dashboard API provides aggregated metrics and system health data for monitoring and visualization.

## Overview

The Dashboard system aggregates data from multiple sources:
- **Workflows**: Volume, status, performance metrics
- **SLAs**: Compliance rates, breach tracking, timing
- **Agents**: Decision activity, acceptance rates, effectiveness
- **Notifications**: Alert counts, critical items

## Architecture

```
┌─────────────────┐
│  Dashboard API  │
└────────┬────────┘
         │
    ┌────┴────┐
    │Dashboard│
    │ Service │
    └────┬────┘
         │
    ┌────┴────────────────────────────┐
    │                                  │
    ▼            ▼          ▼          ▼
┌─────────┐  ┌─────┐  ┌──────┐  ┌──────────┐
│Workflow │  │ SLA │  │Agent │  │Notification│
│ Service │  │Svc  │  │Events│  │  Service   │
└─────────┘  └─────┘  └──────┘  └──────────┘
    │            │         │          │
    └────────────┴─────────┴──────────┘
                   │
              ┌────▼────┐
              │  Event  │
              │  Store  │
              └─────────┘
```

## API Endpoints

### GET /dashboard/overview

Get overall system health snapshot.

**Response:**
```json
{
  "total_workflows": 1250,
  "active_workflows": 85,
  "completed_workflows": 1100,
  "failed_workflows": 65,
  "total_sla_instances": 850,
  "active_slas": 120,
  "sla_breaches_today": 8,
  "sla_compliance_rate": 95.2,
  "unread_notifications": 42,
  "critical_notifications": 5,
  "agent_decisions_today": 67,
  "avg_workflow_completion_hours": 24.5,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /dashboard/sla-metrics

Get SLA-specific metrics and compliance data.

**Query Parameters:**
- `time_range` (optional): `last_hour`, `last_24_hours`, `last_7_days`, `last_30_days`, `last_90_days`
  - Default: `last_24_hours`

**Response:**
```json
{
  "time_range": "last_24_hours",
  "total_slas": 245,
  "met_slas": 230,
  "soft_breaches": 10,
  "hard_breaches": 5,
  "compliance_rate": 93.9,
  "avg_response_time_minutes": 45.0,
  "avg_resolution_time_minutes": 180.0,
  "compliance_trend": "up",
  "breach_trend": "down",
  "by_priority": {
    "high": 80,
    "medium": 120,
    "low": 45
  },
  "by_type": {
    "support_ticket": 150,
    "incident": 60,
    "change_request": 35
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /dashboard/workflow-stats

Get workflow statistics and performance data.

**Query Parameters:**
- `time_range` (optional): Time range for stats (default: `last_7_days`)

**Response:**
```json
{
  "time_range": "last_7_days",
  "total_workflows": 520,
  "created_workflows": 520,
  "completed_workflows": 480,
  "failed_workflows": 15,
  "by_status": {
    "active": 25,
    "completed": 480,
    "failed": 15
  },
  "by_type": {
    "support_ticket": 280,
    "incident": 140,
    "change_request": 70,
    "approval": 30
  },
  "avg_completion_time_hours": 24.5,
  "median_completion_time_hours": 18.0,
  "throughput_per_day": 74.3,
  "throughput_trend": "up",
  "workflows_awaiting_assignment": 12,
  "workflows_escalated": 8,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /dashboard/agent-performance

Get agent performance metrics and effectiveness data.

**Query Parameters:**
- `time_range` (optional): Time range for performance (default: `last_7_days`)

**Response:**
```json
{
  "time_range": "last_7_days",
  "total_decisions": 340,
  "decisions_accepted": 298,
  "decisions_rejected": 42,
  "acceptance_rate": 87.6,
  "workflows_influenced": 215,
  "avg_decision_time_seconds": 2.3,
  "by_decision_type": {
    "escalate": 85,
    "assign": 120,
    "prioritize": 90,
    "recommend": 45
  },
  "decision_quality_score": 87.5,
  "activity_trend": "up",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /dashboard/time-series/{metric_name}

Get time series data for charting.

**Path Parameters:**
- `metric_name`: Metric to retrieve
  - `workflow_volume`: Workflows created over time
  - `sla_breaches`: SLA breaches over time
  - `agent_decisions`: Agent decisions over time

**Query Parameters:**
- `time_range` (optional): Time range for series (default: `last_24_hours`)

**Response:**
```json
{
  "metric_name": "workflow_volume",
  "time_range": "last_24_hours",
  "data_points": [
    {
      "timestamp": "2024-01-15T00:00:00Z",
      "value": 12.0
    },
    {
      "timestamp": "2024-01-15T01:00:00Z",
      "value": 8.0
    },
    // ... more data points
  ],
  "unit": null
}
```

## Data Models

### TimeRange Enum

- `last_hour`: Last 60 minutes
- `last_24_hours`: Last 24 hours
- `last_7_days`: Last 7 days
- `last_30_days`: Last 30 days
- `last_90_days`: Last 90 days
- `custom`: Custom range (not yet implemented)

### MetricTrend Enum

- `up`: Metric is increasing
- `down`: Metric is decreasing
- `stable`: Metric is stable

## Usage Example

```python
import httpx

# Get overview
response = httpx.get(
    "http://api.trustplane.com/api/v1/dashboard/overview",
    headers={"Authorization": "Bearer <token>"}
)
overview = response.json()
print(f"Active workflows: {overview['active_workflows']}")
print(f"SLA compliance: {overview['sla_compliance_rate']}%")

# Get SLA metrics for last 7 days
response = httpx.get(
    "http://api.trustplane.com/api/v1/dashboard/sla-metrics",
    params={"time_range": "last_7_days"},
    headers={"Authorization": "Bearer <token>"}
)
sla_metrics = response.json()
print(f"Compliance rate: {sla_metrics['compliance_rate']}%")
print(f"Breaches: {sla_metrics['hard_breaches']}")

# Get time series for workflow volume
response = httpx.get(
    "http://api.trustplane.com/api/v1/dashboard/time-series/workflow_volume",
    params={"time_range": "last_24_hours"},
    headers={"Authorization": "Bearer <token>"}
)
time_series = response.json()
for point in time_series['data_points']:
    print(f"{point['timestamp']}: {point['value']}")
```

## Performance Considerations

### Current Implementation

The current implementation queries the event store directly and builds projections on-the-fly. This works for moderate loads but has limitations:

- **Query Complexity**: Aggregating across multiple streams is expensive
- **Scalability**: Performance degrades with event volume
- **Real-time**: No caching, every request queries the database

### Production Recommendations

For production deployments with high traffic:

1. **Materialized Views**: Create projection tables that are updated by event handlers
   ```sql
   CREATE TABLE dashboard_metrics (
     org_id UUID,
     metric_type VARCHAR,
     time_bucket TIMESTAMP,
     value JSONB,
     PRIMARY KEY (org_id, metric_type, time_bucket)
   );
   ```

2. **Caching**: Use Redis to cache dashboard data with TTL
   ```python
   @cache(ttl=300)  # 5 minutes
   async def get_overview():
       # ...
   ```

3. **Background Jobs**: Pre-calculate metrics periodically
   ```python
   @scheduler.cron("*/5 * * * *")  # Every 5 minutes
   async def refresh_dashboards():
       for org in orgs:
           await calculate_and_cache_metrics(org)
   ```

4. **Analytics Database**: Use separate OLAP database (ClickHouse, TimescaleDB) for time-series and aggregations

## Multi-Tenancy

The Dashboard service respects tenant isolation:
- All queries are scoped to the organization from the auth token
- Users only see data for their organization
- Cross-tenant data leakage is prevented at the database level (RLS)

## Testing

Run dashboard tests:
```bash
pytest tests/test_dashboard.py -v
```

## Future Enhancements

- **Custom Dashboards**: User-configurable dashboard layouts
- **Drill-Down**: Click-through from metrics to detailed views
- **Alerts**: Threshold-based alerting on metrics
- **Exports**: Export dashboard data to CSV/Excel
- **Real-Time Updates**: WebSocket streaming for live metrics
- **Comparative Analysis**: Compare time periods, teams, or projects
