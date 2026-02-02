"""
Authentication endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import Dict, Any
from datetime import datetime

from app.api.deps import (
    get_tenant_context,
    get_token_payload,
    JWTPayload,
)
from app.core.tenant import TenantContext
from app.schemas.responses import APIResponse

router = APIRouter()


@router.get("/me", response_model=APIResponse)
async def get_current_user(
    tenant: TenantContext = Depends(get_tenant_context)
) -> Dict[str, Any]:
    """
    Get current authenticated user information.
    
    Returns the user profile extracted from the JWT token
    along with their permissions.
    """
    return {
        "success": True,
        "data": {
            "user_id": str(tenant.user_id),
            "org_id": str(tenant.org_id),
            "email": tenant.email,
            "role": tenant.role,
            "permissions": tenant.permissions,
            "authenticated_at": tenant.authenticated_at.isoformat(),
        },
        "timestamp": datetime.utcnow(),
    }


@router.get("/verify")
async def verify_token(
    payload: JWTPayload = Depends(get_token_payload)
) -> Dict[str, Any]:
    """
    Verify if the current token is valid.
    
    This endpoint only validates the token signature and expiration.
    Useful for frontend to check auth status without loading full context.
    """
    return {
        "valid": True,
        "user_id": payload.sub,
        "org_id": payload.org_id,
        "expires_at": datetime.fromtimestamp(payload.exp).isoformat(),
    }


@router.get("/permissions")
async def get_permissions(
    tenant: TenantContext = Depends(get_tenant_context)
) -> Dict[str, Any]:
    """
    Get all permissions for the current user.
    
    Returns a list of permission strings that can be used
    for client-side authorization checks.
    """
    return {
        "success": True,
        "data": {
            "role": tenant.role,
            "permissions": tenant.permissions,
            "is_admin": tenant.is_admin(),
            "is_manager": tenant.is_manager(),
        },
        "timestamp": datetime.utcnow(),
    }


@router.post("/logout")
async def logout(
    tenant: TenantContext = Depends(get_tenant_context)
) -> Dict[str, Any]:
    """
    Logout endpoint.
    
    Note: With JWT auth, tokens can't be invalidated server-side.
    The client should delete the token. This endpoint is for
    audit logging purposes.
    """
    # In a full implementation, you might:
    # 1. Log the logout event to audit
    # 2. Invalidate any server-side sessions
    # 3. Add token to a blacklist (requires Redis/DB)
    
    return {
        "success": True,
        "message": "Logged out successfully",
        "timestamp": datetime.utcnow(),
    }
