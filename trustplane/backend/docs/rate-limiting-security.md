# Rate Limiting & Security Guide

## Overview

TrustPlane implements production-grade rate limiting and security controls:

- **Rate Limiting** - Multiple strategies (Token Bucket, Sliding Window, Fixed Window)
- **Security Headers** - Industry-standard HTTP security headers
- **CORS Protection** - Secure cross-origin resource sharing
- **Request Size Limits** - DoS protection via payload size limits
- **IP Whitelisting** - Admin endpoint protection

## Rate Limiting

### Strategies

#### 1. Token Bucket (Recommended)

Best for: Allowing burst traffic while maintaining average rate

```python
from app.core.rate_limiting import RateLimitConfig, RateLimitStrategy

config = RateLimitConfig(
    requests=100,              # 100 requests
    window_seconds=60,         # per minute
    strategy=RateLimitStrategy.TOKEN_BUCKET,
    burst_size=150             # Allow bursts up to 150
)
```

**Characteristics:**
- ✅ Allows traffic bursts
- ✅ Smooth rate control
- ✅ Tokens refill continuously
- ⚠️ Slightly more complex

#### 2. Sliding Window

Best for: Precise rate control over rolling time windows

```python
config = RateLimitConfig(
    requests=1000,
    window_seconds=3600,       # 1000 per hour
    strategy=RateLimitStrategy.SLIDING_WINDOW
)
```

**Characteristics:**
- ✅ Precise rate limiting
- ✅ No boundary issues
- ⚠️ Higher memory usage
- ⚠️ More CPU intensive

#### 3. Fixed Window

Best for: Simple rate limits with clear reset times

```python
config = RateLimitConfig(
    requests=5,
    window_seconds=300,        # 5 per 5 minutes
    strategy=RateLimitStrategy.FIXED_WINDOW
)
```

**Characteristics:**
- ✅ Simple implementation
- ✅ Low memory usage
- ⚠️ Boundary issues (2x rate at window edges)

### Configuration

#### Global IP Rate Limit

Applies to all requests from the same IP:

```python
from app.core.rate_limiting import rate_limiter, RateLimitConfig

rate_limiter.configure_ip_rate_limit(
    RateLimitConfig(
        requests=100,          # 100 requests per IP
        window_seconds=60,     # per minute
        strategy=RateLimitStrategy.TOKEN_BUCKET
    )
)
```

#### Global User Rate Limit

Applies to authenticated users (higher limits):

```python
rate_limiter.configure_user_rate_limit(
    RateLimitConfig(
        requests=1000,         # 1000 requests per user
        window_seconds=3600,   # per hour
        strategy=RateLimitStrategy.SLIDING_WINDOW
    )
)
```

#### Endpoint-Specific Limits

Protect sensitive endpoints with stricter limits:

```python
# Login endpoint - prevent brute force
rate_limiter.configure_endpoint_rate_limit(
    "/api/auth/login",
    RateLimitConfig(
        requests=5,            # Only 5 attempts
        window_seconds=300,    # per 5 minutes
        strategy=RateLimitStrategy.FIXED_WINDOW
    )
)

# Registration - prevent spam
rate_limiter.configure_endpoint_rate_limit(
    "/api/auth/register",
    RateLimitConfig(
        requests=3,
        window_seconds=3600,   # 3 per hour
        strategy=RateLimitStrategy.FIXED_WINDOW
    )
)

# High-traffic endpoint with burst support
rate_limiter.configure_endpoint_rate_limit(
    "/api/workflows",
    RateLimitConfig(
        requests=50,
        window_seconds=60,
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        burst_size=100         # Allow bursts
    )
)
```

### Default Configurations

TrustPlane comes with sensible defaults:

```python
# In app/core/rate_limiting.py

DEFAULT_IP_RATE_LIMIT = RateLimitConfig(
    requests=100,              # 100 requests per IP
    window_seconds=60,         # per minute
    strategy=RateLimitStrategy.TOKEN_BUCKET
)

DEFAULT_USER_RATE_LIMIT = RateLimitConfig(
    requests=1000,             # 1000 requests per user
    window_seconds=3600,       # per hour
    strategy=RateLimitStrategy.SLIDING_WINDOW
)

ENDPOINT_RATE_LIMITS = {
    "/api/auth/login": RateLimitConfig(
        requests=5, window_seconds=300, strategy=RateLimitStrategy.FIXED_WINDOW
    ),
    "/api/auth/register": RateLimitConfig(
        requests=3, window_seconds=3600, strategy=RateLimitStrategy.FIXED_WINDOW
    ),
    "/api/workflows": RateLimitConfig(
        requests=50, window_seconds=60, strategy=RateLimitStrategy.TOKEN_BUCKET, burst_size=100
    ),
}
```

### Rate Limit Headers

Responses include rate limit information:

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1705584060
```

**Headers:**
- `X-RateLimit-Limit` - Total requests allowed in window
- `X-RateLimit-Remaining` - Requests remaining in current window
- `X-RateLimit-Reset` - Unix timestamp when limit resets

### Rate Limit Exceeded Response

When rate limit is exceeded, clients receive 429 status:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30
X-Error-ID: err_abc123

{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded",
    "category": "rate_limit",
    "retryable": true,
    "details": {
      "limit": 100,
      "window_seconds": 60,
      "retry_after": 30
    }
  }
}
```

### Checking Rate Limits Programmatically

```python
from app.core.rate_limiting import rate_limiter

# Check if request is allowed
allowed, retry_after = rate_limiter.check_rate_limit(
    ip="192.168.1.1",
    user_id="user-123",
    endpoint="/api/workflows"
)

if not allowed:
    # Wait or return error
    print(f"Rate limited. Retry after {retry_after} seconds")

# Get rate limit status
info = rate_limiter.get_rate_limit_info(
    ip="192.168.1.1",
    user_id="user-123"
)

print(f"User limit: {info['user']['limit']}")
print(f"Remaining: {info['user']['remaining']}")
print(f"Reset at: {info['user']['reset_at']}")
```

### Admin Overrides

Reset rate limiters (testing or admin override):

```python
# Reset IP limiter
rate_limiter.reset_limiter(ip="192.168.1.1")

# Reset user limiter
rate_limiter.reset_limiter(user_id="user-123")

# Reset endpoint limiter
rate_limiter.reset_limiter(endpoint="/api/auth/login")
```

## Security Headers

### Automatic Security Headers

All responses include security headers:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: accelerometer=(), camera=(), geolocation=(), ...
Content-Security-Policy: default-src 'self'; script-src 'self'; ...
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Powered-By: TrustPlane
```

### Header Explanations

#### X-Content-Type-Options: nosniff

Prevents MIME type sniffing attacks. Browser must respect declared Content-Type.

#### X-Frame-Options: DENY

Prevents clickjacking by blocking iframe embedding.

#### X-XSS-Protection: 1; mode=block

Enables browser XSS filter and blocks page if attack detected.

#### Referrer-Policy: strict-origin-when-cross-origin

Controls referrer information sent with requests.

#### Permissions-Policy

Disables dangerous browser features:
- Camera access
- Microphone access
- Geolocation
- Payment APIs
- USB devices

#### Content-Security-Policy (CSP)

Prevents XSS and injection attacks by restricting resource sources.

**Default Policy:**
```
default-src 'self';
script-src 'self' 'unsafe-inline' 'unsafe-eval';
style-src 'self' 'unsafe-inline';
img-src 'self' data: https:;
font-src 'self' data:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
```

**Customizing CSP:**

Edit `app/middleware/security.py`:

```python
csp_directives = [
    "default-src 'self'",
    "script-src 'self' https://trusted-cdn.com",
    "style-src 'self' 'unsafe-inline'",
    # Add your directives
]
```

#### Strict-Transport-Security (HSTS)

Forces HTTPS connections. Only enabled in production.

```
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
```

- `max-age=31536000` - 1 year
- `includeSubDomains` - Apply to all subdomains
- `preload` - Eligible for browser HSTS preload list

## CORS Configuration

### Allowed Origins

Configure in `.env`:

```env
# Single origin
ALLOWED_ORIGINS=https://app.trustplane.com

# Multiple origins
ALLOWED_ORIGINS=https://app.trustplane.com,https://staging.trustplane.com

# Wildcard subdomain
ALLOWED_ORIGINS=*.trustplane.com

# Development (allow all)
ALLOWED_ORIGINS=*
```

### CORS Headers

Successful CORS responses include:

```http
Access-Control-Allow-Origin: https://app.trustplane.com
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, X-Request-ID
Access-Control-Expose-Headers: X-RateLimit-Limit, X-Error-ID, X-Request-ID
Access-Control-Max-Age: 600
```

### Preflight Requests

CORS preflight (OPTIONS) requests are handled automatically:

```http
OPTIONS /api/workflows HTTP/1.1
Origin: https://app.trustplane.com
Access-Control-Request-Method: POST
Access-Control-Request-Headers: Authorization, Content-Type

HTTP/1.1 200 OK
Access-Control-Allow-Origin: https://app.trustplane.com
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, X-Request-ID
Access-Control-Max-Age: 600
```

## Request Size Limits

Prevent DoS attacks via large payloads:

```python
# In app/main.py

app.add_middleware(
    RequestSizeLimitMiddleware,
    max_size=10 * 1024 * 1024  # 10MB limit
)
```

Requests exceeding limit receive:

```http
HTTP/1.1 413 Request Entity Too Large

{
  "error": {
    "code": "REQUEST_TOO_LARGE",
    "message": "Request body too large"
  }
}
```

## IP Whitelisting

Protect admin/internal endpoints:

```python
app.add_middleware(
    IPWhitelistMiddleware,
    whitelisted_ips=["192.168.1.0/24", "10.0.0.100"],
    protected_paths=["/admin", "/internal"]
)
```

Non-whitelisted IPs receive:

```http
HTTP/1.1 403 Forbidden

{
  "error": {
    "code": "FORBIDDEN",
    "message": "Access denied"
  }
}
```

## Best Practices

### 1. Layer Rate Limits

Use multiple limit types:

```python
# Global IP limit (prevent single IP abuse)
rate_limiter.configure_ip_rate_limit(...)

# Global user limit (higher for authenticated users)
rate_limiter.configure_user_rate_limit(...)

# Endpoint limits (protect sensitive operations)
rate_limiter.configure_endpoint_rate_limit("/api/auth/login", ...)
```

### 2. Choose Right Strategy

- **Token Bucket** - Most APIs (allows bursts)
- **Sliding Window** - Precise rate control needed
- **Fixed Window** - Simple cases, clear reset times

### 3. Set Appropriate Limits

```python
# Authentication endpoints - strict
"/api/auth/login": 5 requests / 5 minutes

# Public read endpoints - generous
"/api/public/status": 1000 requests / minute

# Write endpoints - moderate
"/api/workflows": 50 requests / minute
```

### 4. Monitor Rate Limit Violations

```python
# In app/middleware/rate_limit.py

logger.warning(
    f"Rate limit exceeded: ip={client_ip}, user={user_id}, "
    f"endpoint={endpoint}"
)
```

Set up alerts for frequent violations.

### 5. Provide Clear Error Messages

Always include `retry_after` and rate limit details in 429 responses.

### 6. Use HTTPS in Production

Security headers like HSTS only work over HTTPS.

### 7. Regularly Review CORS Origins

Keep `ALLOWED_ORIGINS` list updated. Never use `*` in production.

### 8. Test Security Headers

Use tools like:
- [securityheaders.com](https://securityheaders.com)
- [Mozilla Observatory](https://observatory.mozilla.org)

## Production Checklist

- [ ] Configure rate limits for all endpoints
- [ ] Set `ALLOWED_ORIGINS` to specific domains
- [ ] Enable HSTS in production
- [ ] Review and customize CSP directives
- [ ] Set up rate limit monitoring/alerts
- [ ] Configure IP whitelist for admin endpoints
- [ ] Test rate limiting under load
- [ ] Verify security headers score
- [ ] Document rate limits in API docs
- [ ] Set up Redis for distributed rate limiting (future)

## Monitoring

### Rate Limit Metrics

Track in monitoring system:

```python
# Metrics to collect
- rate_limit_exceeded_count{endpoint, user_type}
- rate_limit_remaining{endpoint, user_id}
- rate_limit_reset_time{endpoint}
```

### Security Metrics

```python
# Track security events
- cors_violation_count{origin}
- request_size_exceeded_count
- ip_whitelist_violation_count{ip, path}
```

## Future Enhancements

### Distributed Rate Limiting (Redis)

For multi-instance deployments:

```python
from redis import Redis

class RedisRateLimiter(RateLimiter):
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
    
    # Implement using Redis for shared state
```

### Dynamic Rate Limits

Adjust limits based on user tier:

```python
def get_user_rate_limit(user: User) -> RateLimitConfig:
    if user.tier == "enterprise":
        return RateLimitConfig(requests=10000, window_seconds=3600)
    elif user.tier == "pro":
        return RateLimitConfig(requests=5000, window_seconds=3600)
    else:
        return RateLimitConfig(requests=1000, window_seconds=3600)
```

### Geographic Rate Limiting

Different limits per region:

```python
def get_regional_limit(country_code: str) -> RateLimitConfig:
    if country_code in HIGH_TRAFFIC_REGIONS:
        return STRICTER_LIMIT
    return DEFAULT_LIMIT
```
