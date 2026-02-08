"""
Error Tracking and Reporting

Centralized error tracking, logging, and reporting infrastructure.
"""
import traceback
import sys
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
import logging
from contextvars import ContextVar

from app.core.exceptions import TrustPlaneException, ErrorCategory

logger = logging.getLogger(__name__)

# Context variables for request tracking
request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_context: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
org_id_context: ContextVar[Optional[str]] = ContextVar("org_id", default=None)


class ErrorTracker:
    """
    Error tracking and reporting service.
    
    In production, integrate with services like:
    - Sentry
    - DataDog
    - New Relic
    - CloudWatch
    """
    
    def __init__(self):
        self.errors: list[Dict[str, Any]] = []  # In-memory for development
    
    def track_error(
        self,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None,
        severity: str = "error"
    ) -> str:
        """
        Track an error with context.
        
        Returns error ID for correlation.
        """
        error_id = str(uuid4())
        
        # Extract error details
        error_data = {
            "error_id": error_id,
            "timestamp": datetime.utcnow().isoformat(),
            "severity": severity,
            "exception_type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback.format_exc(),
            "context": context or {},
        }
        
        # Add TrustPlane exception details
        if isinstance(exception, TrustPlaneException):
            error_data.update({
                "code": exception.code,
                "category": exception.category,
                "status_code": exception.status_code,
                "retryable": exception.retryable,
                "details": exception.details,
            })
        
        # Add request context
        error_data["request_context"] = {
            "request_id": request_id_context.get(),
            "user_id": user_id_context.get(),
            "org_id": org_id_context.get(),
        }
        
        # Store error
        self.errors.append(error_data)
        
        # Log error
        log_message = (
            f"Error [{error_id}]: {error_data['exception_type']} - {error_data['message']}"
        )
        
        if severity == "critical":
            logger.critical(log_message, extra=error_data)
        elif severity == "error":
            logger.error(log_message, extra=error_data)
        elif severity == "warning":
            logger.warning(log_message, extra=error_data)
        
        # In production, send to external service
        # self._send_to_sentry(error_data)
        # self._send_to_datadog(error_data)
        
        return error_id
    
    def track_exception(
        self,
        exc_type,
        exc_value,
        exc_traceback,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Track exception from sys.exc_info()"""
        if exc_value:
            return self.track_error(exc_value, context)
        return ""
    
    def get_error(self, error_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve error by ID"""
        for error in self.errors:
            if error["error_id"] == error_id:
                return error
        return None
    
    def get_recent_errors(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
        category: Optional[ErrorCategory] = None
    ) -> list[Dict[str, Any]]:
        """Get recent errors with optional filtering"""
        filtered = self.errors
        
        if severity:
            filtered = [e for e in filtered if e.get("severity") == severity]
        
        if category:
            filtered = [e for e in filtered if e.get("category") == category]
        
        # Return most recent first
        return sorted(
            filtered,
            key=lambda e: e["timestamp"],
            reverse=True
        )[:limit]
    
    def clear_errors(self):
        """Clear all tracked errors (for testing)"""
        self.errors.clear()


# Global error tracker instance
error_tracker = ErrorTracker()


def track_error(
    exception: Exception,
    context: Optional[Dict[str, Any]] = None,
    severity: str = "error"
) -> str:
    """Convenience function to track errors"""
    return error_tracker.track_error(exception, context, severity)


def set_request_context(
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None
):
    """Set request context for error tracking"""
    if request_id:
        request_id_context.set(request_id)
    if user_id:
        user_id_context.set(user_id)
    if org_id:
        org_id_context.set(org_id)


def clear_request_context():
    """Clear request context"""
    request_id_context.set(None)
    user_id_context.set(None)
    org_id_context.set(None)


class ErrorAggregator:
    """
    Aggregates errors for monitoring and alerting.
    """
    
    def __init__(self):
        self.error_counts: Dict[str, int] = {}
        self.error_rates: Dict[str, list] = {}
    
    def record_error(self, error_code: str):
        """Record an error occurrence"""
        self.error_counts[error_code] = self.error_counts.get(error_code, 0) + 1
        
        # Track time for rate calculation
        if error_code not in self.error_rates:
            self.error_rates[error_code] = []
        self.error_rates[error_code].append(datetime.utcnow())
    
    def get_error_count(self, error_code: str) -> int:
        """Get total error count for code"""
        return self.error_counts.get(error_code, 0)
    
    def get_error_rate(
        self,
        error_code: str,
        window_minutes: int = 5
    ) -> float:
        """Get error rate (errors per minute) in time window"""
        if error_code not in self.error_rates:
            return 0.0
        
        cutoff = datetime.utcnow().timestamp() - (window_minutes * 60)
        recent_errors = [
            e for e in self.error_rates[error_code]
            if e.timestamp() > cutoff
        ]
        
        if not recent_errors:
            return 0.0
        
        return len(recent_errors) / window_minutes
    
    def get_top_errors(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get most frequent errors"""
        return sorted(
            self.error_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]


# Global error aggregator
error_aggregator = ErrorAggregator()


def setup_error_handlers():
    """Setup global error handlers"""
    
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions"""
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't track keyboard interrupts
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        # Track the error
        error_tracker.track_exception(
            exc_type,
            exc_value,
            exc_traceback,
            context={"source": "uncaught_exception"}
        )
        
        # Call default handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    # Set up global exception hook
    sys.excepthook = handle_uncaught_exception
    
    logger.info("Error handlers configured")
