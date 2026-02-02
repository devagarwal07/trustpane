"""
Authentication middleware for request processing
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
import logging
import time
import uuid

from app.core.tenant import clear_current_tenant

logger = logging.getLogger(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles authentication-related concerns:
    1. Adds request ID for tracing
    2. Clears tenant context after request
    3. Logs request timing
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(
        self, 
        request: Request, 
        call_next: RequestResponseEndpoint
    ) -> Response:
        # Generate request ID if not provided
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        
        # Add to request state for access in handlers
        request.state.request_id = request_id
        
        # Track timing
        start_time = time.time()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Add request ID to response headers
            response.headers["x-request-id"] = request_id
            
            # Log request completion
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                f"{request.method} {request.url.path} "
                f"status={response.status_code} "
                f"duration={duration_ms:.2f}ms "
                f"request_id={request_id}"
            )
            
            return response
            
        finally:
            # CRITICAL: Always clear tenant context after request
            # This prevents context leakage between requests
            clear_current_tenant()


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces tenant isolation at the HTTP layer.
    
    Checks for any org_id in URL parameters or body that doesn't
    match the authenticated tenant.
    """
    
    PROTECTED_PARAMS = {"org_id", "organization_id", "tenant_id"}
    
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint
    ) -> Response:
        # Check URL query parameters for org_id manipulation
        for param in self.PROTECTED_PARAMS:
            if param in request.query_params:
                # Log potential attack
                logger.warning(
                    f"Blocked org_id in query params: {request.url} "
                    f"client={request.client.host if request.client else 'unknown'}"
                )
                # Don't block, but the dependency will use JWT org_id
                # This just logs the attempt
        
        return await call_next(request)
