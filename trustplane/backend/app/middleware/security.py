"""
Security Headers Middleware
Implements security best practices with HTTP headers
"""
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response"""
        response = await call_next(request)
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking attacks
        response.headers["X-Frame-Options"] = "DENY"
        
        # Enable XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )
        
        # Content Security Policy
        if not settings.DEBUG:
            csp_directives = [
                "default-src 'self'",
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # Adjust for your needs
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data: https:",
                "font-src 'self' data:",
                "connect-src 'self'",
                "frame-ancestors 'none'",
                "base-uri 'self'",
                "form-action 'self'"
            ]
            response.headers["Content-Security-Policy"] = "; ".join(csp_directives)
        
        # HSTS (HTTP Strict Transport Security) - only in production with HTTPS
        if not settings.DEBUG and settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        
        # Remove server header (don't reveal server info)
        if "Server" in response.headers:
            del response.headers["Server"]
        
        # Add custom security header
        response.headers["X-Powered-By"] = "TrustPlane"
        
        return response


class CORSSecurityMiddleware(BaseHTTPMiddleware):
    """
    Enhanced CORS middleware with security checks
    """
    
    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: list = None,
        allow_credentials: bool = True,
        max_age: int = 600
    ):
        super().__init__(app)
        self.allowed_origins = allowed_origins or []
        self.allow_credentials = allow_credentials
        self.max_age = max_age
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Handle CORS with security checks"""
        
        # Get origin from request
        origin = request.headers.get("origin")
        
        # Handle preflight requests
        if request.method == "OPTIONS":
            response = Response(status_code=200)
        else:
            response = await call_next(request)
        
        # Check if origin is allowed
        if origin and self._is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            
            if self.allow_credentials:
                response.headers["Access-Control-Allow-Credentials"] = "true"
            
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            )
            
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-Request-ID, X-Correlation-ID"
            )
            
            response.headers["Access-Control-Expose-Headers"] = (
                "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, "
                "X-Error-ID, X-Request-ID"
            )
            
            response.headers["Access-Control-Max-Age"] = str(self.max_age)
        
        return response
    
    def _is_origin_allowed(self, origin: str) -> bool:
        """Check if origin is in allowed list"""
        # Allow all origins in development
        if settings.DEBUG:
            return True
        
        # Check exact matches
        if origin in self.allowed_origins:
            return True
        
        # Check wildcard patterns
        for allowed in self.allowed_origins:
            if allowed == "*":
                return True
            if allowed.startswith("*."):
                # Match subdomain pattern
                domain = allowed[2:]
                if origin.endswith(domain):
                    return True
        
        return False


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit request body size
    Prevents DoS attacks via large payloads
    """
    
    def __init__(self, app: ASGIApp, max_size: int = 10 * 1024 * 1024):  # 10MB default
        super().__init__(app)
        self.max_size = max_size
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check request size before processing"""
        
        # Get content length from headers
        content_length = request.headers.get("content-length")
        
        if content_length:
            content_length = int(content_length)
            
            if content_length > self.max_size:
                return Response(
                    content='{"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body too large"}}',
                    status_code=413,
                    media_type="application/json"
                )
        
        return await call_next(request)


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    IP whitelist middleware for admin endpoints
    """
    
    def __init__(
        self,
        app: ASGIApp,
        whitelisted_ips: list = None,
        protected_paths: list = None
    ):
        super().__init__(app)
        self.whitelisted_ips = set(whitelisted_ips or [])
        self.protected_paths = protected_paths or ["/admin", "/internal"]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check IP whitelist for protected paths"""
        
        # Check if path is protected
        path = request.url.path
        is_protected = any(path.startswith(p) for p in self.protected_paths)
        
        if is_protected:
            # Get client IP
            client_ip = self._get_client_ip(request)
            
            # Check if IP is whitelisted
            if client_ip not in self.whitelisted_ips:
                return Response(
                    content='{"error": {"code": "FORBIDDEN", "message": "Access denied"}}',
                    status_code=403,
                    media_type="application/json"
                )
        
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        if request.client:
            return request.client.host
        
        return "unknown"
