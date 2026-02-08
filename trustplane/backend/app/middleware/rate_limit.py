"""
Rate Limiting Middleware
"""
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

from app.core.rate_limiting import rate_limiter
from app.core.exceptions import RateLimitExceededError

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting requests
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limits before processing request"""
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Get user ID if authenticated
        user_id = None
        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id
        
        # Get endpoint path
        endpoint = request.url.path
        
        # Check rate limit
        allowed, retry_after = rate_limiter.check_rate_limit(
            ip=client_ip,
            user_id=user_id,
            endpoint=endpoint
        )
        
        if not allowed:
            # Log rate limit violation
            logger.warning(
                f"Rate limit exceeded: ip={client_ip}, user={user_id}, "
                f"endpoint={endpoint}, retry_after={retry_after}"
            )
            
            # Get rate limit info for headers
            rate_info = rate_limiter.get_rate_limit_info(
                ip=client_ip,
                user_id=user_id,
                endpoint=endpoint
            )
            
            # Determine limit and window for error message
            limit = 100
            window = 60
            
            if "user" in rate_info:
                limit = rate_info["user"]["limit"]
                window = rate_info["user"]["window_seconds"]
            elif "ip" in rate_info:
                limit = rate_info["ip"]["limit"]
                window = rate_info["ip"]["window_seconds"]
            
            # Raise rate limit exception
            raise RateLimitExceededError(
                limit=limit,
                window_seconds=window,
                retry_after=int(retry_after) if retry_after else 60
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        self._add_rate_limit_headers(response, client_ip, user_id, endpoint)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request"""
        # Check X-Forwarded-For header (proxy/load balancer)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take first IP (client IP)
            return forwarded.split(",")[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct connection IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _add_rate_limit_headers(
        self,
        response: Response,
        ip: str,
        user_id: Optional[str],
        endpoint: str
    ) -> None:
        """Add rate limit information to response headers"""
        rate_info = rate_limiter.get_rate_limit_info(
            ip=ip,
            user_id=user_id,
            endpoint=endpoint
        )
        
        # Use user rate limit info if available, otherwise IP
        info = rate_info.get("user") or rate_info.get("ip")
        
        if info:
            response.headers["X-RateLimit-Limit"] = str(info["limit"])
            response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
            response.headers["X-RateLimit-Reset"] = str(int(info["reset_at"]))
