"""
Tenant Context - Multi-tenant isolation layer
Ensures all operations are scoped to the authenticated tenant
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from uuid import UUID
from contextvars import ContextVar
from datetime import datetime

from app.core.exceptions import TenantIsolationError


@dataclass
class TenantContext:
    """
    Tenant context containing all information needed for
    tenant-scoped operations.
    
    This is injected into every request and used to:
    1. Filter all database queries by org_id
    2. Validate cross-tenant access attempts
    3. Provide actor information for audit logs
    4. Scope AI agent operations
    """
    
    # Required tenant info
    org_id: UUID
    user_id: UUID
    
    # User details
    email: str
    role: str
    
    # Permissions (loaded from database)
    permissions: List[str] = field(default_factory=list)
    
    # Request metadata
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Timestamps
    authenticated_at: datetime = field(default_factory=datetime.utcnow)
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission"""
        # Admins have all permissions
        if self.role == "admin":
            return True
        return permission in self.permissions
    
    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions"""
        if self.role == "admin":
            return True
        return any(p in self.permissions for p in permissions)
    
    def has_all_permissions(self, permissions: List[str]) -> bool:
        """Check if user has all specified permissions"""
        if self.role == "admin":
            return True
        return all(p in self.permissions for p in permissions)
    
    def is_admin(self) -> bool:
        """Check if user is an admin"""
        return self.role == "admin"
    
    def is_manager(self) -> bool:
        """Check if user is a manager or higher"""
        return self.role in ["admin", "manager"]
    
    def validate_org_access(self, target_org_id: UUID) -> None:
        """
        Validate that the current tenant can access the target org.
        Raises TenantIsolationError if access is denied.
        """
        if self.org_id != target_org_id:
            raise TenantIsolationError(
                f"Access denied: Cannot access organization {target_org_id}"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "org_id": str(self.org_id),
            "user_id": str(self.user_id),
            "email": self.email,
            "role": self.role,
            "permissions": self.permissions,
            "request_id": self.request_id,
            "authenticated_at": self.authenticated_at.isoformat(),
        }
    
    def to_audit_context(self) -> Dict[str, Any]:
        """Extract context for audit logging"""
        return {
            "actor_id": str(self.user_id),
            "actor_type": "user",
            "actor_email": self.email,
            "org_id": str(self.org_id),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
        }


# Context variable for async request-scoped tenant context
_tenant_context_var: ContextVar[Optional[TenantContext]] = ContextVar(
    "tenant_context", 
    default=None
)


def get_current_tenant() -> Optional[TenantContext]:
    """Get the current tenant context from context var"""
    return _tenant_context_var.get()


def set_current_tenant(context: TenantContext) -> None:
    """Set the current tenant context"""
    _tenant_context_var.set(context)


def clear_current_tenant() -> None:
    """Clear the current tenant context"""
    _tenant_context_var.set(None)


class TenantContextManager:
    """
    Context manager for tenant context.
    Ensures context is properly set and cleared.
    """
    
    def __init__(self, context: TenantContext):
        self.context = context
        self.token = None
    
    def __enter__(self) -> TenantContext:
        self.token = _tenant_context_var.set(self.context)
        return self.context
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        _tenant_context_var.reset(self.token)
        return False


def require_tenant() -> TenantContext:
    """
    Get the current tenant context or raise an error.
    Use this in code that requires tenant context.
    """
    context = get_current_tenant()
    if context is None:
        raise TenantIsolationError("No tenant context available")
    return context
