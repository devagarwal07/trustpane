"""
Global exception handlers for production-safe error responses
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
import traceback
from datetime import datetime

from app.core.exceptions import (
    TrustPlaneException,
    AuthenticationError,
    AuthorizationError,
    TenantIsolationError,
    ValidationError,
    EventStoreError,
    IntegrityError,
)
from app.core.tenant import get_current_tenant

logger = logging.getLogger(__name__)


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict = None,
    request_id: str = None
) -> JSONResponse:
    """Create a standardized error response"""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
            },
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request_id,
        }
    )


async def trustplane_exception_handler(
    request: Request, 
    exc: TrustPlaneException
) -> JSONResponse:
    """Handle TrustPlane custom exceptions"""
    request_id = getattr(request.state, "request_id", None)
    tenant = get_current_tenant()
    
    # Log with context
    logger.error(
        f"TrustPlane error: {exc.code} - {exc.message}",
        extra={
            "code": exc.code,
            "details": exc.details,
            "request_id": request_id,
            "org_id": str(tenant.org_id) if tenant else None,
            "user_id": str(tenant.user_id) if tenant else None,
        }
    )
    
    # Map exception types to status codes
    status_map = {
        AuthenticationError: 401,
        AuthorizationError: 403,
        TenantIsolationError: 403,
        ValidationError: 400,
        EventStoreError: 500,
        IntegrityError: 500,
    }
    
    status_code = status_map.get(type(exc), 500)
    
    return create_error_response(
        status_code=status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details if status_code != 500 else {},
        request_id=request_id,
    )


async def authentication_error_handler(
    request: Request,
    exc: AuthenticationError
) -> JSONResponse:
    """Handle authentication errors - don't leak details"""
    request_id = getattr(request.state, "request_id", None)
    
    logger.warning(f"Authentication failed: {exc.message}")
    
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
    
    # Log full error for debugging
    logger.exception(
        f"Unhandled exception: {type(exc).__name__}",
        extra={
            "request_id": request_id,
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
        details={"request_id": request_id},  # Only include request ID for support
        request_id=request_id,
    )
