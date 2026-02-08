# API Documentation Guide

## Overview

TrustPlane API is a RESTful API with comprehensive OpenAPI/Swagger documentation. All endpoints are versioned under `/api/v1` prefix.

## Base URLs

- **Production**: `https://api.trustplane.com`
- **Staging**: `https://staging-api.trustplane.com`
- **Development**: `http://localhost:8000`

## Interactive Documentation

- **Swagger UI**: `https://api.trustplane.com/docs`
- **ReDoc**: `https://api.trustplane.com/redoc`
- **OpenAPI Spec**: `https://api.trustplane.com/api/v1/openapi.json`

## Authentication

All API requests (except `/health` and authentication endpoints) require a valid JWT token.

### Obtaining a Token

```bash
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "user-123",
    "email": "user@example.com",
    "org_id": "org-456"
  }
}
```

### Using the Token

Include the token in the `Authorization` header:

```bash
GET /api/v1/slas
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

## API Endpoints

### Authentication

#### POST /api/v1/auth/register

Register a new user account.

**Request:**

```json
{
  "email": "newuser@example.com",
  "password": "SecureP@ssw0rd",
  "full_name": "John Doe",
  "org_name": "Acme Corp"
}
```

**Response:** `201 Created`

```json
{
  "message": "User registered successfully",
  "user_id": "user-789"
}
```

**Rate Limit:** 3 requests per hour per IP

#### POST /api/v1/auth/login

Authenticate and obtain access token.

**Rate Limit:** 5 requests per 5 minutes per IP

#### POST /api/v1/auth/refresh

Refresh an expired access token.

#### GET /api/v1/auth/me

Get current user information.

**Response:**

```json
{
  "id": "user-123",
  "email": "user@example.com",
  "full_name": "John Doe",
  "org_id": "org-456",
  "role": "admin",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### SLAs

#### GET /api/v1/slas

List all SLAs for the organization.

**Query Parameters:**

- `status` (optional): Filter by status (`active`, `draft`, `expired`)
- `skip` (optional): Pagination offset (default: 0)
- `limit` (optional): Results per page (default: 50, max: 100)

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "sla-123",
      "name": "Premium SLA",
      "tier": "premium",
      "response_time_minutes": 60,
      "resolution_time_hours": 24,
      "uptime_percentage": 99.9,
      "status": "active",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 15,
  "skip": 0,
  "limit": 50
}
```

#### POST /api/v1/slas

Create a new SLA.

**Request:**

```json
{
  "name": "Enterprise SLA",
  "tier": "enterprise",
  "response_time_minutes": 30,
  "resolution_time_hours": 12,
  "uptime_percentage": 99.95,
  "support_hours": "24/7",
  "escalation_policy": {
    "first_level": 30,
    "second_level": 60,
    "manager_level": 120
  }
}
```

**Response:** `201 Created`

#### GET /api/v1/slas/{sla_id}

Get specific SLA details.

#### PUT /api/v1/slas/{sla_id}

Update an existing SLA.

#### DELETE /api/v1/slas/{sla_id}

Delete an SLA (soft delete).

### Workflows

#### POST /api/v1/workflows

Create a new workflow.

**Request:**

```json
{
  "name": "Support Ticket Workflow",
  "type": "support_ticket",
  "sla_id": "sla-123",
  "metadata": {
    "priority": "high",
    "customer_id": "customer-456"
  }
}
```

**Response:** `201 Created`

```json
{
  "id": "workflow-789",
  "name": "Support Ticket Workflow",
  "status": "pending",
  "state": "created",
  "sla_id": "sla-123",
  "created_at": "2024-01-15T12:00:00Z"
}
```

#### POST /api/v1/workflows/{workflow_id}/transition

Transition workflow to new state.

**Request:**

```json
{
  "new_state": "in_progress",
  "metadata": {
    "assigned_to": "agent-001"
  }
}
```

#### GET /api/v1/workflows/{workflow_id}/events

Get workflow event history.

**Response:**

```json
{
  "events": [
    {
      "id": "event-001",
      "type": "workflow.created",
      "data": {...},
      "timestamp": "2024-01-15T12:00:00Z"
    },
    {
      "id": "event-002",
      "type": "workflow.state_changed",
      "data": {
        "old_state": "pending",
        "new_state": "in_progress"
      },
      "timestamp": "2024-01-15T12:05:00Z"
    }
  ]
}
```

### Tickets

#### POST /api/v1/tickets

Create a support ticket.

**Request:**

```json
{
  "title": "Application Error 500",
  "description": "Users experiencing 500 errors on checkout page",
  "priority": "high",
  "category": "technical",
  "workflow_id": "workflow-789"
}
```

**Response:** `201 Created`

#### GET /api/v1/tickets/{ticket_id}

Get ticket details with SLA tracking.

**Response:**

```json
{
  "id": "ticket-123",
  "title": "Application Error 500",
  "status": "open",
  "priority": "high",
  "sla_compliance": {
    "response_deadline": "2024-01-15T13:00:00Z",
    "resolution_deadline": "2024-01-16T12:00:00Z",
    "time_remaining": "45 minutes",
    "is_breached": false
  },
  "assigned_to": "agent-001",
  "created_at": "2024-01-15T12:00:00Z"
}
```

#### POST /api/v1/tickets/{ticket_id}/comments

Add comment to ticket.

#### PATCH /api/v1/tickets/{ticket_id}/status

Update ticket status.

### Agents

#### POST /api/v1/agents/execute

Execute an AI agent task.

**Request:**

```json
{
  "agent_type": "support_analyzer",
  "task_data": {
    "ticket_id": "ticket-123",
    "action": "analyze_logs"
  },
  "priority": "normal"
}
```

**Response:** `202 Accepted`

```json
{
  "task_id": "task-456",
  "status": "queued",
  "estimated_completion": "2024-01-15T12:10:00Z"
}
```

#### GET /api/v1/agents/tasks/{task_id}

Get agent task status and results.

### Analytics

#### GET /api/v1/analytics/sla-compliance

Get SLA compliance metrics.

**Query Parameters:**

- `start_date` (required): Start date (ISO 8601)
- `end_date` (required): End date (ISO 8601)
- `sla_id` (optional): Filter by SLA

**Response:**

```json
{
  "compliance_rate": 98.5,
  "total_workflows": 1250,
  "compliant": 1231,
  "breached": 19,
  "by_sla": [
    {
      "sla_id": "sla-123",
      "sla_name": "Premium SLA",
      "compliance_rate": 99.2,
      "total": 500,
      "compliant": 496,
      "breached": 4
    }
  ],
  "trend": [
    {"date": "2024-01-01", "rate": 98.1},
    {"date": "2024-01-02", "rate": 98.5}
  ]
}
```

#### GET /api/v1/analytics/dashboard

Get unified dashboard data.

**Response:**

```json
{
  "summary": {
    "active_workflows": 125,
    "open_tickets": 45,
    "sla_compliance": 98.5,
    "avg_resolution_time": "18.5 hours"
  },
  "charts": {
    "tickets_by_priority": {...},
    "workflows_by_state": {...},
    "agent_performance": {...}
  },
  "alerts": [
    {
      "type": "sla_breach_warning",
      "workflow_id": "workflow-999",
      "time_remaining": "15 minutes"
    }
  ]
}
```

### Notifications

#### POST /api/v1/notifications/send

Send a notification.

**Request:**

```json
{
  "channel": "slack",
  "recipient": "#alerts",
  "subject": "SLA Breach Alert",
  "message": "Workflow workflow-999 is about to breach SLA",
  "priority": "high",
  "metadata": {
    "workflow_id": "workflow-999"
  }
}
```

#### GET /api/v1/notifications/channels

Get configured notification channels.

### Events

#### GET /api/v1/events

Query event store with filters.

**Query Parameters:**

- `stream_id` (optional): Filter by stream
- `event_type` (optional): Filter by event type
- `start_date` (optional): Events after date
- `end_date` (optional): Events before date

#### POST /api/v1/events/replay

Replay events for debugging/recovery.

## Response Formats

### Success Response

```json
{
  "data": {...},
  "metadata": {
    "request_id": "req-abc123",
    "timestamp": "2024-01-15T12:00:00Z"
  }
}
```

### Error Response

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Workflow not found",
    "category": "validation",
    "retryable": false,
    "details": {
      "resource_type": "workflow",
      "resource_id": "workflow-999"
    },
    "error_id": "err-def456",
    "timestamp": "2024-01-15T12:00:00Z"
  }
}
```

## HTTP Status Codes

- `200 OK` - Request successful
- `201 Created` - Resource created
- `202 Accepted` - Request accepted (async processing)
- `204 No Content` - Success with no response body
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Missing or invalid authentication
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource conflict (duplicate, concurrent update)
- `422 Unprocessable Entity` - Validation error
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Service temporarily unavailable

## Rate Limiting

All endpoints are rate limited. Rate limit information is included in response headers:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1705584060
```

When rate limit is exceeded:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

### Default Limits

- **Global (per IP)**: 100 requests/minute
- **Global (per user)**: 1000 requests/hour
- **Auth endpoints**: 5 requests/5 minutes
- **Registration**: 3 requests/hour

## Pagination

List endpoints support pagination:

```
GET /api/v1/slas?skip=0&limit=50
```

**Response:**

```json
{
  "items": [...],
  "total": 250,
  "skip": 0,
  "limit": 50,
  "has_more": true
}
```

## Filtering & Sorting

Many endpoints support filtering:

```
GET /api/v1/workflows?status=active&priority=high&sort=-created_at
```

**Sort Options:**

- `created_at` - Ascending
- `-created_at` - Descending

## WebSocket API

Connect to WebSocket for real-time updates:

```javascript
const ws = new WebSocket('wss://api.trustplane.com/ws?token=YOUR_JWT_TOKEN');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data);
};

// Subscribe to events
ws.send(JSON.stringify({
  type: 'subscribe',
  channels: ['workflow.updates', 'sla.breaches']
}));
```

## Code Examples

### Python

```python
import requests

# Login
response = requests.post(
    'https://api.trustplane.com/api/v1/auth/login',
    json={'email': 'user@example.com', 'password': 'password'}
)
token = response.json()['access_token']

# Make authenticated request
headers = {'Authorization': f'Bearer {token}'}
response = requests.get(
    'https://api.trustplane.com/api/v1/slas',
    headers=headers
)
slas = response.json()
```

### JavaScript

```javascript
// Login
const loginResponse = await fetch('https://api.trustplane.com/api/v1/auth/login', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    email: 'user@example.com',
    password: 'password'
  })
});
const {access_token} = await loginResponse.json();

// Make authenticated request
const response = await fetch('https://api.trustplane.com/api/v1/slas', {
  headers: {'Authorization': `Bearer ${access_token}`}
});
const slas = await response.json();
```

### cURL

```bash
# Login
TOKEN=$(curl -s -X POST https://api.trustplane.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password"}' \
  | jq -r '.access_token')

# List SLAs
curl -H "Authorization: Bearer $TOKEN" \
  https://api.trustplane.com/api/v1/slas
```

## Best Practices

1. **Cache tokens** - Tokens are valid for 30 minutes
2. **Handle rate limits** - Implement exponential backoff
3. **Use pagination** - Don't fetch all records at once
4. **Check error codes** - Use `error.retryable` flag
5. **Store error_id** - Include in support requests
6. **Use WebSockets** - For real-time updates
7. **Set timeouts** - 30s for requests, 5m for webhooks

## Webhooks

Configure webhooks to receive event notifications:

```json
POST /api/v1/webhooks
{
  "url": "https://your-app.com/webhooks/trustplane",
  "events": ["workflow.completed", "sla.breached"],
  "secret": "your-webhook-secret"
}
```

**Webhook Payload:**

```json
{
  "event_id": "evt-123",
  "event_type": "workflow.completed",
  "timestamp": "2024-01-15T12:00:00Z",
  "data": {
    "workflow_id": "workflow-789",
    "status": "completed"
  },
  "signature": "sha256=..."
}
```

## Support

- **Status Page**: https://status.trustplane.com
- **Email**: api-support@trustplane.com
- **Discord**: https://discord.gg/trustplane
- **GitHub Issues**: https://github.com/trustplane/api/issues
