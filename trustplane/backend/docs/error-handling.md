# Error Handling Guide

## Overview

TrustPlane implements a comprehensive error handling system with:
- **Hierarchical exceptions** - Structured exception types with proper HTTP status codes
- **Error tracking** - Centralized tracking with unique error IDs
- **Retry logic** - Automatic retry with exponential backoff for transient failures
- **Circuit breakers** - Protection against cascading failures
- **Error aggregation** - Metrics and monitoring support

## Exception Hierarchy

### Base Exception

All TrustPlane exceptions inherit from `TrustPlaneException`:

```python
from app.core.exceptions import TrustPlaneException, ErrorCategory

class TrustPlaneException(Exception):
    def __init__(
        self,
        message: str,
        code: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
        category: ErrorCategory = ErrorCategory.SYSTEM,
        retryable: bool = False
    )
```

**Attributes:**
- `message` - Human-readable error description
- `code` - Machine-readable error code (e.g., "VALIDATION_ERROR")
- `details` - Additional context (field names, resource IDs, etc.)
- `status_code` - HTTP status code (400, 404, 500, etc.)
- `category` - Error category for monitoring/alerting
- `retryable` - Whether clients should retry the request

### Error Categories

```python
class ErrorCategory(str, Enum):
    AUTH = "authentication"           # Authentication failures
    AUTHZ = "authorization"          # Authorization/permission failures
    VALIDATION = "validation"         # Input validation errors
    BUSINESS_LOGIC = "business_logic" # Business rule violations
    DATA_INTEGRITY = "data_integrity" # Data consistency issues
    EXTERNAL_SERVICE = "external_service" # External API failures
    SYSTEM = "system"                 # Internal system errors
    RATE_LIMIT = "rate_limit"        # Rate limiting
```

### Common Exceptions

#### Authentication & Authorization

```python
from app.core.exceptions import (
    AuthenticationError, InvalidTokenError, MissingTokenError,
    AuthorizationError, TenantIsolationError
)

# Missing or invalid authentication
raise AuthenticationError("Invalid credentials")

# Invalid JWT token
raise InvalidTokenError("Token expired", token_type="JWT")

# Missing authorization header
raise MissingTokenError()

# Insufficient permissions
raise AuthorizationError(
    action="delete_workflow",
    resource="workflow:abc123"
)

# Tenant boundary violation
raise TenantIsolationError(
    org_id="org-123",
    attempted_access="org-456"
)
```

#### Validation Errors

```python
from app.core.exceptions import ValidationError, InvalidStateTransitionError

# Input validation failure
raise ValidationError("Invalid email format", field="email")

# Invalid state transition
raise InvalidStateTransitionError(
    entity="workflow",
    entity_id="wf-123",
    current_state="completed",
    attempted_state="pending"
)
```

#### Resource Errors

```python
from app.core.exceptions import (
    ResourceNotFoundError, ResourceConflictError,
    DuplicateResourceError
)

# Resource not found
raise ResourceNotFoundError("workflow", workflow_id)

# Resource conflict (concurrent updates)
raise ResourceConflictError("workflow", workflow_id, "Another update in progress")

# Duplicate resource (unique constraint)
raise DuplicateResourceError("SLA", {"name": "Premium SLA"})
```

#### Data Integrity

```python
from app.core.exceptions import (
    ConcurrencyError, IntegrityError, HashChainBrokenError
)

# Optimistic locking failure
raise ConcurrencyError(
    stream_id="workflow-123",
    expected_version=5,
    actual_version=6
)

# Database constraint violation
raise IntegrityError("Foreign key violation", constraint="fk_org_id")

# Event sourcing integrity
raise HashChainBrokenError(
    stream_id="workflow-123",
    event_sequence=10,
    expected_hash="abc...",
    actual_hash="def..."
)
```

#### External Services

```python
from app.core.exceptions import (
    AgentError, AgentTimeoutError, ExternalServiceError
)

# AI agent failure
raise AgentError("agent-001", "Agent crashed", {"last_state": "processing"})

# Agent timeout (retryable)
raise AgentTimeoutError("agent-001", timeout_seconds=30)

# External API failure
raise ExternalServiceError("Slack API", "Rate limited", retryable=True)
```

#### Rate Limiting

```python
from app.core.exceptions import RateLimitExceededError

# Rate limit exceeded
raise RateLimitExceededError(
    limit=100,
    window_seconds=60,
    retry_after=30
)
```

## Retry Logic

### Basic Retry

Automatically retry transient failures with exponential backoff:

```python
from app.core.resilience import with_retry, RetryConfig

@with_retry(RetryConfig(
    max_attempts=3,              # Maximum retry attempts
    initial_delay=1.0,           # Initial delay in seconds
    max_delay=60.0,              # Maximum delay between retries
    exponential_base=2.0,        # Backoff multiplier
    jitter=True,                 # Add randomness to delays
    retryable_exceptions=(       # Exceptions that trigger retry
        AgentTimeoutError,
        ExternalServiceError,
    )
))
async def call_external_api():
    # Will retry on AgentTimeoutError or ExternalServiceError
    response = await api_client.fetch_data()
    return response
```

**Retry Behavior:**
- **Retryable exceptions**: Automatically retried (timeouts, 5xx errors, network issues)
- **Non-retryable exceptions**: Not retried (validation errors, 4xx errors, auth failures)
- **Exponential backoff**: Delays increase exponentially (1s, 2s, 4s, 8s...)
- **Jitter**: Random variation prevents thundering herd

### Default Configuration

```python
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True,
    retryable_exceptions=(
        AgentTimeoutError,
        ExternalServiceError,
        DatabaseError,
        ServiceUnavailableError,
        ConcurrencyError,
    )
)
```

## Circuit Breaker

### Purpose

Circuit breakers prevent cascading failures by "opening" when a service is unhealthy:

```python
from app.core.resilience import with_circuit_breaker, get_circuit_breaker

@with_circuit_breaker("slack_api")
async def send_slack_notification(message: str):
    # Protected by circuit breaker
    await slack_client.send(message)
```

### States

1. **CLOSED** - Normal operation, requests pass through
2. **OPEN** - Service unhealthy, requests fail immediately
3. **HALF_OPEN** - Testing if service recovered, limited requests allowed

### Configuration

```python
from app.core.resilience import CircuitBreakerConfig

CircuitBreakerConfig(
    failure_threshold=5,        # Failures before opening circuit
    success_threshold=2,        # Successes to close circuit
    timeout=60.0,               # Seconds before trying half-open
    expected_exception=ExternalServiceError  # Exception that triggers failure
)
```

### Manual Circuit Breaker

```python
from app.core.resilience import get_circuit_breaker, CircuitBreakerState

breaker = get_circuit_breaker("external_service")

# Check state
if breaker.state == CircuitBreakerState.OPEN:
    # Service is down, use fallback
    return cached_data

# Call through circuit breaker
try:
    result = await breaker.call_async(external_call)
except ServiceUnavailableError:
    # Circuit is open, use fallback
    result = fallback_value
```

## Combined Resilience

Use both retry and circuit breaker for maximum resilience:

```python
from app.core.resilience import with_resilience, RetryConfig

@with_resilience(
    retry_config=RetryConfig(max_attempts=3, initial_delay=1.0),
    circuit_breaker_name="payment_api"
)
async def process_payment(payment_id: str):
    # Protected by both retry logic and circuit breaker
    result = await payment_api.charge(payment_id)
    return result
```

## Error Tracking

### Automatic Tracking

All exceptions are automatically tracked with unique error IDs:

```python
# Exception handlers automatically track errors
@app.exception_handler(TrustPlaneException)
async def handle_exception(request, exc):
    error_id = track_error(exc, context={"request_id": request.state.request_id})
    # error_id returned to client for support reference
```

### Manual Tracking

Track errors manually for custom scenarios:

```python
from app.core.error_tracking import track_error, error_tracker

try:
    result = risky_operation()
except Exception as exc:
    error_id = track_error(
        exc,
        context={"user_id": user_id, "org_id": org_id},
        severity="critical"
    )
    logger.error(f"Operation failed: {error_id}")
    raise
```

### Retrieve Error Details

```python
from app.core.error_tracking import error_tracker

# Get specific error
error = error_tracker.get_error(error_id)

# Get recent errors
recent_errors = error_tracker.get_recent_errors(limit=10)
```

### Error Aggregation

Monitor error rates and patterns:

```python
from app.core.error_tracking import error_aggregator

# Record error for metrics
error_aggregator.record_error("VALIDATION_ERROR")

# Get error counts
count = error_aggregator.get_error_count("VALIDATION_ERROR")

# Get error rate (errors per minute)
rate = error_aggregator.get_error_rate("VALIDATION_ERROR")

# Get top errors
top_errors = error_aggregator.get_top_errors(limit=10)
# [(error_code, count), ...]
```

## Error Response Format

All errors return consistent JSON:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid email format",
    "category": "validation",
    "retryable": false,
    "details": {
      "field": "email",
      "provided_value": "invalid-email"
    },
    "error_id": "err_abc123def456",
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

**Headers:**
- `X-Error-ID: err_abc123def456` - Unique error identifier for support
- `Retry-After: 30` - Seconds to wait before retrying (for 429/503 errors)

## Best Practices

### 1. Use Specific Exceptions

```python
# ❌ Bad - Generic exception
raise Exception("User not found")

# ✅ Good - Specific exception with context
raise ResourceNotFoundError("user", user_id)
```

### 2. Include Context in Details

```python
# ❌ Bad - Minimal information
raise ValidationError("Invalid input")

# ✅ Good - Detailed context
raise ValidationError(
    "Email format is invalid",
    field="email",
    provided_value=email,
    expected_format="user@domain.com"
)
```

### 3. Set Retryable Correctly

```python
# Transient failures - retryable
raise AgentTimeoutError("agent-001", timeout_seconds=30)  # retryable=True

# Permanent failures - not retryable
raise ValidationError("Invalid email format")  # retryable=False
```

### 4. Use Retry for External Services

```python
# Always use retry for external calls
@with_retry(DEFAULT_RETRY_CONFIG)
async def call_external_api():
    return await api_client.fetch()
```

### 5. Use Circuit Breakers for Critical Dependencies

```python
# Protect against cascading failures
@with_circuit_breaker("payment_gateway")
async def charge_customer(amount: Decimal):
    return await payment_api.charge(amount)
```

### 6. Log Error IDs

```python
try:
    result = operation()
except TrustPlaneException as exc:
    error_id = track_error(exc)
    logger.error(f"Operation failed: {error_id}", exc_info=True)
    raise
```

## Monitoring Integration

### Sentry

```python
# In app/core/error_tracking.py
import sentry_sdk

# Configure in setup_error_handlers()
if settings.SENTRY_DSN:
    sentry_sdk.capture_exception(exc)
```

### DataDog

```python
from ddtrace import tracer

# Add to error tracking
tracer.current_span().set_tag("error_id", error_id)
tracer.current_span().set_tag("error_code", exc.code)
```

### Custom Metrics

```python
from prometheus_client import Counter

error_counter = Counter(
    "trustplane_errors_total",
    "Total errors by code",
    ["error_code", "category"]
)

# Increment on error
error_counter.labels(
    error_code=exc.code,
    category=exc.category
).inc()
```

## Testing Error Handling

```python
import pytest
from app.core.exceptions import ResourceNotFoundError

@pytest.mark.asyncio
async def test_resource_not_found():
    with pytest.raises(ResourceNotFoundError) as exc_info:
        await get_workflow("nonexistent-id")
    
    assert exc_info.value.status_code == 404
    assert "nonexistent-id" in str(exc_info.value)
    assert exc_info.value.retryable is False
```

## Summary

- **Use specific exceptions** with proper error codes and categories
- **Track all errors** with unique IDs for debugging and support
- **Retry transient failures** automatically with exponential backoff
- **Protect critical services** with circuit breakers
- **Monitor error rates** and patterns for alerting
- **Return consistent error responses** with helpful context
- **Never expose internal details** in production error messages
