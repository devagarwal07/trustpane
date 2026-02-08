"""
Custom exceptions for TrustPlane

Comprehensive exception hierarchy with error codes, 
HTTP status mapping, and detailed error information.
"""
from typing import Optional, Dict, Any
from enum import Enum


class ErrorCategory(str, Enum):
    """Error categories for classification"""
    AUTH = "authentication"
    AUTHZ = "authorization"
    VALIDATION = "validation"
    BUSINESS_LOGIC = "business_logic"
    DATA_INTEGRITY = "data_integrity"
    EXTERNAL_SERVICE = "external_service"
    SYSTEM = "system"
    RATE_LIMIT = "rate_limit"


class TrustPlaneException(Exception):
    """
    Base exception for all TrustPlane errors
    
    Attributes:
        message: Human-readable error message
        code: Machine-readable error code
        details: Additional error context
        status_code: HTTP status code
        category: Error category
        retryable: Whether the operation can be retried
    """
    
    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 500,
        category: ErrorCategory = ErrorCategory.SYSTEM,
        retryable: bool = False
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.status_code = status_code
        self.category = category
        self.retryable = retryable
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to JSON-serializable dict"""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "category": self.category,
                "details": self.details,
                "retryable": self.retryable
            }
        }


# =====================================================
# AUTHENTICATION & AUTHORIZATION ERRORS
# =====================================================

class AuthenticationError(TrustPlaneException):
    """Authentication failures"""
    
    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="AUTH_ERROR",
            details=details,
            status_code=401,
            category=ErrorCategory.AUTH,
            retryable=False
        )


class InvalidTokenError(AuthenticationError):
    """Invalid or expired JWT token"""
    
    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__(message, details={"reason": "invalid_token"})


class MissingTokenError(AuthenticationError):
    """Missing authentication token"""
    
    def __init__(self, message: str = "Authentication token required"):
        super().__init__(message, details={"reason": "missing_token"})


class AuthorizationError(TrustPlaneException):
    """Authorization/permission failures"""
    
    def __init__(
        self,
        message: str = "Permission denied",
        required_permission: Optional[str] = None
    ):
        details = {"required_permission": required_permission} if required_permission else {}
        super().__init__(
            message,
            code="AUTHZ_ERROR",
            details=details,
            status_code=403,
            category=ErrorCategory.AUTHZ,
            retryable=False
        )


class TenantIsolationError(TrustPlaneException):
    """Cross-tenant access attempts"""
    
    def __init__(
        self,
        message: str = "Tenant isolation violation",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="TENANT_ISOLATION_ERROR",
            details=details,
            status_code=403,
            category=ErrorCategory.AUTHZ,
            retryable=False
        )


# =====================================================
# VALIDATION ERRORS
# =====================================================

class ValidationError(TrustPlaneException):
    """Input validation failures"""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        error_details = details or {}
        if field:
            error_details["field"] = field
        
        super().__init__(
            message,
            code="VALIDATION_ERROR",
            details=error_details,
            status_code=400,
            category=ErrorCategory.VALIDATION,
            retryable=False
        )


class InvalidStateTransitionError(ValidationError):
    """Invalid workflow/SLA state transition"""
    
    def __init__(
        self,
        current_state: str,
        requested_state: str,
        entity_type: str = "workflow"
    ):
        super().__init__(
            f"Cannot transition {entity_type} from {current_state} to {requested_state}",
            details={
                "current_state": current_state,
                "requested_state": requested_state,
                "entity_type": entity_type
            }
        )


class DuplicateResourceError(ValidationError):
    """Attempt to create duplicate resource"""
    
    def __init__(
        self,
        resource_type: str,
        identifier: str
    ):
        super().__init__(
            f"{resource_type} already exists: {identifier}",
            details={
                "resource_type": resource_type,
                "identifier": identifier
            }
        )


# =====================================================
# RESOURCE ERRORS
# =====================================================

class ResourceNotFoundError(TrustPlaneException):
    """Resource not found"""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None
    ):
        error_details = details or {}
        error_details.update({
            "resource_type": resource_type,
            "resource_id": resource_id
        })
        
        super().__init__(
            f"{resource_type} not found: {resource_id}",
            code="RESOURCE_NOT_FOUND",
            details=error_details,
            status_code=404,
            category=ErrorCategory.BUSINESS_LOGIC,
            retryable=False
        )


class ResourceConflictError(TrustPlaneException):
    """Resource state conflict"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="RESOURCE_CONFLICT",
            details=details,
            status_code=409,
            category=ErrorCategory.BUSINESS_LOGIC,
            retryable=True
        )


# =====================================================
# EVENT STORE & DATA INTEGRITY
# =====================================================

class EventStoreError(TrustPlaneException):
    """Event store operation failures"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True
    ):
        super().__init__(
            message,
            code="EVENT_STORE_ERROR",
            details=details,
            status_code=500,
            category=ErrorCategory.DATA_INTEGRITY,
            retryable=retryable
        )


class ConcurrencyError(EventStoreError):
    """Concurrent modification detected"""
    
    def __init__(
        self,
        stream_id: str,
        expected_version: int,
        actual_version: int
    ):
        super().__init__(
            f"Concurrent modification on stream {stream_id}",
            details={
                "stream_id": stream_id,
                "expected_version": expected_version,
                "actual_version": actual_version
            },
            retryable=True
        )


class IntegrityError(TrustPlaneException):
    """Data integrity violations (hash chain broken, etc.)"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="INTEGRITY_ERROR",
            details=details,
            status_code=500,
            category=ErrorCategory.DATA_INTEGRITY,
            retryable=False
        )


class HashChainBrokenError(IntegrityError):
    """Event hash chain integrity violation"""
    
    def __init__(
        self,
        stream_id: str,
        event_id: str,
        expected_hash: str,
        actual_hash: str
    ):
        super().__init__(
            f"Hash chain broken at event {event_id}",
            details={
                "stream_id": stream_id,
                "event_id": event_id,
                "expected_hash": expected_hash,
                "actual_hash": actual_hash
            }
        )


# =====================================================
# BUSINESS LOGIC ERRORS
# =====================================================

class SLAError(TrustPlaneException):
    """SLA engine errors"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="SLA_ERROR",
            details=details,
            status_code=400,
            category=ErrorCategory.BUSINESS_LOGIC,
            retryable=False
        )


class SLAAlreadyExistsError(SLAError):
    """SLA already attached to workflow"""
    
    def __init__(self, workflow_id: str, sla_id: str):
        super().__init__(
            f"SLA already exists for workflow {workflow_id}",
            details={"workflow_id": workflow_id, "sla_id": sla_id}
        )


class PolicyError(TrustPlaneException):
    """Policy engine errors"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message,
            code="POLICY_ERROR",
            details=details,
            status_code=400,
            category=ErrorCategory.BUSINESS_LOGIC,
            retryable=False
        )


class PolicyEvaluationError(PolicyError):
    """Policy evaluation failure"""
    
    def __init__(self, policy_id: str, reason: str):
        super().__init__(
            f"Failed to evaluate policy {policy_id}: {reason}",
            details={"policy_id": policy_id, "reason": reason}
        )


# =====================================================
# EXTERNAL SERVICE ERRORS
# =====================================================

class AgentError(TrustPlaneException):
    """AI agent errors"""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True
    ):
        super().__init__(
            message,
            code="AGENT_ERROR",
            details=details,
            status_code=503,
            category=ErrorCategory.EXTERNAL_SERVICE,
            retryable=retryable
        )


class AgentTimeoutError(AgentError):
    """Agent decision timeout"""
    
    def __init__(self, timeout_seconds: int):
        super().__init__(
            f"Agent decision timed out after {timeout_seconds}s",
            details={"timeout_seconds": timeout_seconds},
            retryable=True
        )


class ExternalServiceError(TrustPlaneException):
    """External service (database, API) errors"""
    
    def __init__(
        self,
        service_name: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True
    ):
        error_details = details or {}
        error_details["service_name"] = service_name
        
        super().__init__(
            f"{service_name} error: {message}",
            code="EXTERNAL_SERVICE_ERROR",
            details=error_details,
            status_code=503,
            category=ErrorCategory.EXTERNAL_SERVICE,
            retryable=retryable
        )


class DatabaseError(ExternalServiceError):
    """Database operation failures"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("database", message, details, retryable=True)


class SupabaseError(ExternalServiceError):
    """Supabase-specific errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("supabase", message, details, retryable=True)


# =====================================================
# RATE LIMITING
# =====================================================

class RateLimitExceededError(TrustPlaneException):
    """Rate limit exceeded"""
    
    def __init__(
        self,
        limit: int,
        window_seconds: int,
        retry_after: int
    ):
        super().__init__(
            f"Rate limit exceeded: {limit} requests per {window_seconds}s",
            code="RATE_LIMIT_EXCEEDED",
            details={
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after": retry_after
            },
            status_code=429,
            category=ErrorCategory.RATE_LIMIT,
            retryable=True
        )


# =====================================================
# SYSTEM ERRORS
# =====================================================

class ConfigurationError(TrustPlaneException):
    """System configuration errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="CONFIGURATION_ERROR",
            details=details,
            status_code=500,
            category=ErrorCategory.SYSTEM,
            retryable=False
        )


class ServiceUnavailableError(TrustPlaneException):
    """Service temporarily unavailable"""
    
    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        retry_after: Optional[int] = None
    ):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(
            message,
            code="SERVICE_UNAVAILABLE",
            details=details,
            status_code=503,
            category=ErrorCategory.SYSTEM,
            retryable=True
        )

