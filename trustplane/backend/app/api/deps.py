"""
API Dependencies - Authentication, tenant context, database sessions

This module provides FastAPI dependencies for:
1. JWT authentication via Supabase
2. Tenant context injection for multi-tenant isolation
3. Permission and role-based access control
4. Database session management
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any, List
from uuid import UUID
import logging

from app.core.config import settings
from app.core.auth import supabase_auth, JWTPayload
from app.core.tenant import (
    TenantContext, 
    set_current_tenant, 
    get_current_tenant,
    TenantContextManager
)
from app.core.exceptions import (
    AuthenticationError, 
    AuthorizationError,
    TenantIsolationError
)
from app.db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(
    scheme_name="Supabase JWT",
    description="Enter your Supabase access token",
    auto_error=True
)

# Optional security for public endpoints
optional_security = HTTPBearer(
    scheme_name="Supabase JWT",
    description="Optional authentication",
    auto_error=False
)


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> JWTPayload:
    """
    Validate Supabase JWT and return decoded payload.
    
    This is the first step in the authentication chain.
    Validates the token signature and expiration.
    """
    try:
        token = credentials.credentials
        payload = supabase_auth.decode_token(token)
        return payload
    except AuthenticationError as e:
        logger.warning(f"Authentication failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_optional_token_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)
) -> Optional[JWTPayload]:
    """
    Optionally validate JWT for endpoints that support anonymous access.
    Returns None if no token provided.
    """
    if credentials is None:
        return None
    
    try:
        return supabase_auth.decode_token(credentials.credentials)
    except AuthenticationError:
        return None


async def load_user_permissions(
    user_id: str,
    org_id: str
) -> List[str]:
    """
    Load user permissions from database.
    
    This queries the user's roles and aggregates all permissions.
    Cached per-request for efficiency.
    """
    try:
        client = get_supabase_client()
        
        # Get user's roles and their permissions
        # This is a join across user_roles -> roles -> role_permissions -> permissions
        result = client.rpc(
            'get_user_permissions',
            {'p_user_id': user_id, 'p_org_id': org_id}
        ).execute()
        
        if result.data:
            return [p['permission_id'] for p in result.data]
        return []
    except Exception as e:
        logger.warning(f"Failed to load permissions: {e}")
        # Return empty permissions on error - fail closed
        return []


async def get_tenant_context(
    request: Request,
    payload: JWTPayload = Depends(get_token_payload)
) -> TenantContext:
    """
    Build and inject tenant context from authenticated JWT.
    
    This is THE CRITICAL dependency for multi-tenant isolation.
    Every authenticated endpoint MUST use this dependency.
    
    The tenant context:
    1. Validates org_id exists in token
    2. Loads user permissions from database
    3. Creates TenantContext with all needed info
    4. Sets context in context var for background access
    """
    # Validate org_id is present
    if not payload.org_id:
        logger.error(f"No org_id in token for user {payload.sub}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization context. Please contact support.",
        )
    
    try:
        org_id = UUID(payload.org_id)
        user_id = UUID(payload.sub)
    except ValueError as e:
        logger.error(f"Invalid UUID in token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )
    
    # Load permissions from database
    permissions = await load_user_permissions(payload.sub, payload.org_id)
    
    # Extract request metadata for audit
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = request.headers.get("x-request-id")
    
    # Build tenant context
    context = TenantContext(
        org_id=org_id,
        user_id=user_id,
        email=payload.email or "",
        role=payload.role,
        permissions=permissions,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    
    # Set in context var for access in non-request code
    set_current_tenant(context)
    
    logger.debug(f"Tenant context set: org={org_id}, user={user_id}, role={payload.role}")
    
    return context


async def get_optional_tenant_context(
    request: Request,
    payload: Optional[JWTPayload] = Depends(get_optional_token_payload)
) -> Optional[TenantContext]:
    """
    Get tenant context if authenticated, None otherwise.
    For endpoints that support both authenticated and anonymous access.
    """
    if payload is None:
        return None
    
    if not payload.org_id:
        return None
    
    try:
        org_id = UUID(payload.org_id)
        user_id = UUID(payload.sub)
    except ValueError:
        return None
    
    permissions = await load_user_permissions(payload.sub, payload.org_id)
    
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    context = TenantContext(
        org_id=org_id,
        user_id=user_id,
        email=payload.email or "",
        role=payload.role,
        permissions=permissions,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    
    set_current_tenant(context)
    return context


def require_permission(permission: str):
    """
    Dependency factory that requires a specific permission.
    
    Usage:
        @router.post("/workflows")
        async def create_workflow(
            tenant: TenantContext = Depends(require_permission("workflow:create"))
        ):
            ...
    """
    async def check_permission(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        if not tenant.has_permission(permission):
            logger.warning(
                f"Permission denied: user={tenant.user_id} "
                f"required={permission} has={tenant.permissions}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return tenant
    
    return check_permission


def require_any_permission(*permissions: str):
    """
    Dependency factory that requires any of the specified permissions.
    
    Usage:
        @router.get("/workflows/{id}")
        async def get_workflow(
            tenant: TenantContext = Depends(require_any_permission("workflow:read", "workflow:admin"))
        ):
            ...
    """
    async def check_permission(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        if not tenant.has_any_permission(list(permissions)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these permissions required: {', '.join(permissions)}"
            )
        return tenant
    
    return check_permission


def require_all_permissions(*permissions: str):
    """
    Dependency factory that requires all specified permissions.
    """
    async def check_permission(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        if not tenant.has_all_permissions(list(permissions)):
            missing = [p for p in permissions if p not in tenant.permissions]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permissions: {', '.join(missing)}"
            )
        return tenant
    
    return check_permission


def require_role(role: str):
    """
    Dependency factory that requires a specific role.
    
    Usage:
        @router.delete("/users/{id}")
        async def delete_user(
            tenant: TenantContext = Depends(require_role("admin"))
        ):
            ...
    """
    role_hierarchy = {
        "viewer": 0,
        "member": 1,
        "manager": 2,
        "admin": 3,
    }
    
    async def check_role(
        tenant: TenantContext = Depends(get_tenant_context)
    ) -> TenantContext:
        user_level = role_hierarchy.get(tenant.role, 0)
        required_level = role_hierarchy.get(role, 999)
        
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role} (you have: {tenant.role})"
            )
        return tenant
    
    return check_role


def require_admin():
    """Shorthand for require_role("admin")"""
    return require_role("admin")


def require_manager():
    """Shorthand for require_role("manager")"""
    return require_role("manager")


class TenantScopedQuery:
    """
    Dependency that provides tenant-scoped database queries.
    
    Automatically adds org_id filter to all queries.
    """
    
    def __init__(self, tenant: TenantContext):
        self.tenant = tenant
        self.org_id = tenant.org_id
    
    def filter_dict(self, **kwargs) -> Dict[str, Any]:
        """Add org_id to filter dictionary"""
        return {"org_id": str(self.org_id), **kwargs}
    
    def validate_resource_org(self, resource_org_id: UUID) -> None:
        """Validate a resource belongs to the current tenant"""
        self.tenant.validate_org_access(resource_org_id)


async def get_tenant_query(
    tenant: TenantContext = Depends(get_tenant_context)
) -> TenantScopedQuery:
    """Get a tenant-scoped query helper"""
    return TenantScopedQuery(tenant)
