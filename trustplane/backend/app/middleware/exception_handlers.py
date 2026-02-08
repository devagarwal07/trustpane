"""
Global exception handlers for production-safe error responses

Enhanced with error tracking, retry hints, and comprehensive logging.
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
import traceback
from datetime import datetime
from typing import Optional

from app.core.exceptions import (
    TrustPlaneException,
    AuthenticationError,
    AuthorizationError,
    TenantIsolationError,
    ValidationError,
    EventStoreError,
    IntegrityError,
    RateLimitExceededError,
)
from app.core.tenant import get_current_tenant
from app.core.error_tracking import track_error, error_aggregator

logger = logging.getLogger(__name__)


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[dict] = None,
    request_id: Optional[str] = None,
    error_id: Optional[str] = None,
    retryable: bool = False,
    retry_after: Optional[int] = None
) -> JSONResponse:
    """Create a standardized error response with tracking"""
    headers = {}
    
    # Add retry-after header if specified
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    
    # Add request ID header
    if request_id:
        headers["X-Request-ID"] = request_id
    
    # Add error ID for tracking
    if error_id:
        headers["X-Error-ID"] = error_id
    
    response_body = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
        },
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
    }
    
    # Include error ID in production for support
    if error_id:
        response_body["error"]["error_id"] = error_id
    
    return JSONResponse(
        status_code=status_code,
        content=response_body,
        headers=headers
    )


async def trustplane_exception_handler(
    request: Request, 
    exc: TrustPlaneException
) -> JSONResponse:
    """Handle TrustPlane custom exceptions with tracking"""
    request_id = getattr(request.state, "request_id", None)
    tenant = get_current_tenant()
    
    # Track error
    error_id = track_error(
        exc,
        context={
            "request_path": str(request.url),
            "request_method": request.method,
            "org_id": str(tenant.org_id) if tenant else None,
            "user_id": str(tenant.user_id) if tenant else None,
        },
        severity="error" if exc.status_code >= 500 else "warning"
    )
    
    # Aggregate error stats
    error_aggregator.record_error(exc.code)
    
    # Log with context
    logger.error(
        f"TrustPlane error: {exc.code} - {exc.message}",
        extra={
            "code": exc.code,
            "category": exc.category,
            "details": exc.details,
            "request_id": request_id,
            "error_id": error_id,
            "org_id": str(tenant.org_id) if tenant else None,
            "user_id": str(tenant.user_id) if tenant else None,
        }
    )
    
    # Don't leak internal details in production for 5xx errors
    details = exc.details if exc.status_code < 500 else {}
    
    return create_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=details,
        request_id=request_id,
        error_id=error_id,
        retryable=exc.retryable,
        retry_after=exc.details.get("retry_after")
    )


async def authentication_error_handler(
    request: Request,
    exc: AuthenticationError
) -> JSONResponse:
    """Handle authentication errors - don't leak details"""
    request_id = getattr(request.state, "request_id", None)
    
    error_id = track_error(
        exc,
        context={"request_path": str(request.url)},
        severity="warning"
    )
    
    logger.warning(
        f"Authentication failed: {exc.message}",
        extra={"request_id": request_id, "error_id": error_id}
    )
    
    return create_error_response(
        status_code=401,
        code="AUTH_ERROR",
        message="Authentication required",  # Generic message
        request_id=request_id,
    )


async def tenant_isolation_error_handler(
    request: Request,
    exc: TenantIsolationError
) -> JSONResponse:
    """Handle tenant isolation violations - security critical"""
    request_id = getattr(request.state, "request_id", None)
    tenant = get_current_tenant()
    
    # Log security event
    logger.critical(
        f"TENANT ISOLATION VIOLATION: {exc.message}",
        extra={
            "request_id": request_id,
            "org_id": str(tenant.org_id) if tenant else None,
            "user_id": str(tenant.user_id) if tenant else None,
            "path": request.url.path,
            "method": request.method,
        }
    )
    
    # Generic response - don't confirm the resource exists
    return create_error_response(
        status_code=403,
        code="ACCESS_DENIED",
        message="Access denied",
        request_id=request_id,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors"""
    request_id = getattr(request.state, "request_id", None)
    
    # Format validation errors
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    
    return create_error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": errors},
        request_id=request_id,
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException
) -> JSONResponse:
    """Handle FastAPI HTTP exceptions"""
    request_id = getattr(request.state, "request_id", None)
    
    return create_error_response(
        status_code=exc.status_code,
        code=f"HTTP_{exc.status_code}",
        message=exc.detail if isinstance(exc.detail, str) else "Request failed",
        request_id=request_id,
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception
) -> JSONResponse:
    """Handle any unhandled exceptions - never leak internals"""
    request_id = getattr(request.state, "request_id", None)
    tenant = get_current_tenant()
    
    # Track error
    error_id = track_error(
        exc,
        context={
            "request_path": str(request.url),
            "request_method": request.method,
            "org_id": str(tenant.org_id) if tenant else None,
            "user_id": str(tenant.user_id) if tenant else None,
        },
        severity="critical"
    )
    
    # Log full error for debugging
    logger.exception(
        f"Unhandled exception: {type(exc).__name__}",
        extra={
            "request_id": request_id,
            "error_id": error_id,
            "org_id": str(tenant.org_id) if tenant else None,
            "path": request.url.path,
            "method": request.method,
            "traceback": traceback.format_exc(),
        }
    )
    
    # Generic response - never expose internals
    return create_error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred. Please try again or contact support.",
        details={"support_reference": error_id},  # Include error ID for support
        request_id=request_id,
        error_id=error_id,
        retryable=True
    )
