"""
Custom exceptions for TrustPlane
"""
from typing import Optional, Dict, Any


class TrustPlaneException(Exception):
    """Base exception for all TrustPlane errors"""
    
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(TrustPlaneException):
    """Authentication failures"""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTH_ERROR")


class AuthorizationError(TrustPlaneException):
    """Authorization/permission failures"""
    
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, code="AUTHZ_ERROR")


class TenantIsolationError(TrustPlaneException):
    """Cross-tenant access attempts"""
    
    def __init__(self, message: str = "Tenant isolation violation"):
        super().__init__(message, code="TENANT_ISOLATION_ERROR")


class ValidationError(TrustPlaneException):
    """Input validation failures"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="VALIDATION_ERROR", details=details)


class EventStoreError(TrustPlaneException):
    """Event store operation failures"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="EVENT_STORE_ERROR", details=details)


class IntegrityError(TrustPlaneException):
    """Data integrity violations (hash chain broken, etc.)"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="INTEGRITY_ERROR", details=details)


class SLAError(TrustPlaneException):
    """SLA engine errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="SLA_ERROR", details=details)


class PolicyError(TrustPlaneException):
    """Policy engine errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="POLICY_ERROR", details=details)


class AgentError(TrustPlaneException):
    """AI agent errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="AGENT_ERROR", details=details)
