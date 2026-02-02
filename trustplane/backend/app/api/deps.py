"""
API Dependencies - Authentication, tenant context, database sessions
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
from dataclasses import dataclass

from app.core.exceptions import AuthenticationError, TenantIsolationError

security = HTTPBearer()


@dataclass
class TenantContext:
    """Tenant context extracted from JWT"""
    org_id: str
    user_id: str
    email: str
    role: str
    permissions: list


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    Validate JWT and extract user information.
    Will be implemented with Supabase JWT validation.
    """
    # Placeholder - will be implemented in Step 4
    token = credentials.credentials
    
    # TODO: Validate Supabase JWT
    # TODO: Extract claims
    
    return {
        "user_id": "placeholder",
        "email": "placeholder@example.com",
        "org_id": "placeholder_org",
        "role": "member"
    }


async def get_tenant_context(
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> TenantContext:
    """
    Extract and validate tenant context from authenticated user.
    This is the foundation of multi-tenant isolation.
    """
    org_id = current_user.get("org_id")
    
    if not org_id:
        raise TenantIsolationError("No organization context found")
    
    return TenantContext(
        org_id=org_id,
        user_id=current_user.get("user_id", ""),
        email=current_user.get("email", ""),
        role=current_user.get("role", "member"),
        permissions=current_user.get("permissions", [])
    )


def require_permission(permission: str):
    """Dependency factory for permission checking"""
    
    async def check_permission(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        if permission not in tenant.permissions and tenant.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return tenant
    
    return check_permission


def require_role(role: str):
    """Dependency factory for role checking"""
    
    async def check_role(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        if tenant.role != role and tenant.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role}"
            )
        return tenant
    
    return check_role
