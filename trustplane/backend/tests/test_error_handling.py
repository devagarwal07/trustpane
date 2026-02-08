"""
Tests for Error Handling and Resilience
"""
import pytest
import asyncio
from uuid import uuid4

from app.core.exceptions import (
    TrustPlaneException, ValidationError, ResourceNotFoundError,
    ConcurrencyError, AgentTimeoutError, RateLimitExceededError,
    ServiceUnavailableError, ErrorCategory
)
from app.core.resilience import (
    RetryConfig, CircuitBreakerConfig, CircuitBreaker, CircuitBreakerState,
    with_retry, with_circuit_breaker, with_resilience
)
from app.core.error_tracking import (
    ErrorTracker, error_tracker, error_aggregator, track_error
)


class TestExceptions:
    """Test exception hierarchy"""
    
    def test_base_exception_attributes(self):
        """Test base exception has all required attributes"""
        exc = TrustPlaneException(
            message="Test error",
            code="TEST_ERROR",
            details={"key": "value"},
            status_code=400,
            category=ErrorCategory.VALIDATION,
            retryable=True
        )
        
        assert exc.message == "Test error"
        assert exc.code == "TEST_ERROR"
        assert exc.details == {"key": "value"}
        assert exc.status_code == 400
        assert exc.category == ErrorCategory.VALIDATION
        assert exc.retryable is True
    
    def test_exception_to_dict(self):
        """Test exception serialization"""
        exc = ValidationError("Invalid input", field="email")
        
        result = exc.to_dict()
        
        assert result["error"]["code"] == "VALIDATION_ERROR"
        assert result["error"]["message"] == "Invalid input"
        assert result["error"]["category"] == ErrorCategory.VALIDATION
        assert "field" in result["error"]["details"]
    
    def test_resource_not_found(self):
        """Test ResourceNotFoundError"""
        exc = ResourceNotFoundError("workflow", "123e4567")
        
        assert exc.status_code == 404
        assert "workflow" in exc.message
        assert "123e4567" in exc.message
        assert exc.details["resource_type"] == "workflow"
        assert exc.details["resource_id"] == "123e4567"
    
    def test_concurrency_error(self):
        """Test ConcurrencyError"""
        exc = ConcurrencyError(
            stream_id="stream-123",
            expected_version=5,
            actual_version=6
        )
        
        assert exc.retryable is True
        assert exc.details["expected_version"] == 5
        assert exc.details["actual_version"] == 6
    
    def test_rate_limit_error(self):
        """Test RateLimitExceededError"""
        exc = RateLimitExceededError(
            limit=100,
            window_seconds=60,
            retry_after=30
        )
        
        assert exc.status_code == 429
        assert exc.retryable is True
        assert exc.details["retry_after"] == 30


@pytest.mark.asyncio
class TestRetryLogic:
    """Test retry decorator"""
    
    async def test_successful_first_attempt(self):
        """Test no retry on success"""
        call_count = 0
        
        @with_retry(RetryConfig(max_attempts=3))
        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await successful_func()
        
        assert result == "success"
        assert call_count == 1
    
    async def test_retry_on_failure(self):
        """Test retry on transient failure"""
        call_count = 0
        
        @with_retry(RetryConfig(
            max_attempts=3,
            initial_delay=0.01,
            retryable_exceptions=(RuntimeError,)
        ))
        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Transient error")
            return "success"
        
        result = await failing_func()
        
        assert result == "success"
        assert call_count == 3
    
    async def test_no_retry_on_non_retryable(self):
        """Test no retry for non-retryable exceptions"""
        call_count = 0
        
        @with_retry(RetryConfig(max_attempts=3))
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValidationError("Invalid input")
        
        with pytest.raises(ValidationError):
            await failing_func()
        
        assert call_count == 1  # Should not retry
    
    async def test_exponential_backoff(self):
        """Test exponential backoff timing"""
        import time
        
        call_times = []
        
        @with_retry(RetryConfig(
            max_attempts=3,
            initial_delay=0.1,
            exponential_base=2.0,
            jitter=False
        ))
        async def failing_func():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise RuntimeError("Transient")
            return "success"
        
        await failing_func()
        
        # Check delays are approximately exponential
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        
        assert delay1 >= 0.1
        assert delay2 >= 0.2


@pytest.mark.asyncio
class TestCircuitBreaker:
    """Test circuit breaker pattern"""
    
    async def test_circuit_remains_closed_on_success(self):
        """Test circuit stays closed with successful calls"""
        breaker = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        
        async def successful_func():
            return "success"
        
        # Multiple successful calls
        for _ in range(5):
            result = await breaker.call_async(successful_func)
            assert result == "success"
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.failure_count == 0
    
    async def test_circuit_opens_on_failures(self):
        """Test circuit opens after threshold failures"""
        breaker = CircuitBreaker(
            "test",
            CircuitBreakerConfig(failure_threshold=3, expected_exception=RuntimeError)
        )
        
        async def failing_func():
            raise RuntimeError("Service down")
        
        # Trigger failures until circuit opens
        for i in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call_async(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Circuit should reject requests
        with pytest.raises(ServiceUnavailableError):
            await breaker.call_async(failing_func)
    
    async def test_circuit_half_open_recovery(self):
        """Test circuit transitions to half-open for recovery"""
        breaker = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=2,
                success_threshold=2,
                timeout=0.1,  # Short timeout for testing
                expected_exception=RuntimeError
            )
        )
        
        # Open circuit
        async def failing_func():
            raise RuntimeError("Fail")
        
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call_async(failing_func)
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Wait for timeout
        await asyncio.sleep(0.15)
        
        # Should transition to half-open
        async def recovering_func():
            return "recovering"
        
        result = await breaker.call_async(recovering_func)
        assert result == "recovering"
        assert breaker.state == CircuitBreakerState.HALF_OPEN


@pytest.mark.asyncio
class TestErrorTracking:
    """Test error tracking system"""
    
    def setup_method(self):
        """Clear error tracker before each test"""
        error_tracker.clear_errors()
    
    def test_track_simple_exception(self):
        """Test tracking a simple exception"""
        exc = RuntimeError("Test error")
        
        error_id = track_error(exc, severity="error")
        
        assert error_id is not None
        error = error_tracker.get_error(error_id)
        assert error is not None
        assert error["exception_type"] == "RuntimeError"
        assert error["message"] == "Test error"
        assert error["severity"] == "error"
    
    def test_track_trustplane_exception(self):
        """Test tracking TrustPlane exception with details"""
        exc = ValidationError("Invalid email", field="email")
        
        error_id = track_error(exc, context={"user_id": "123"})
        
        error = error_tracker.get_error(error_id)
        assert error["code"] == "VALIDATION_ERROR"
        assert error["category"] == ErrorCategory.VALIDATION
        assert error["retryable"] is False
        assert "field" in error["details"]
        assert error["context"]["user_id"] == "123"
    
    def test_error_aggregation(self):
        """Test error counting and aggregation"""
        # Record multiple errors
        for _ in range(5):
            error_aggregator.record_error("VALIDATION_ERROR")
        
        for _ in range(3):
            error_aggregator.record_error("AUTH_ERROR")
        
        # Check counts
        assert error_aggregator.get_error_count("VALIDATION_ERROR") == 5
        assert error_aggregator.get_error_count("AUTH_ERROR") == 3
        
        # Check top errors
        top_errors = error_aggregator.get_top_errors(limit=2)
        assert top_errors[0] == ("VALIDATION_ERROR", 5)
        assert top_errors[1] == ("AUTH_ERROR", 3)
    
    def test_get_recent_errors(self):
        """Test retrieving recent errors"""
        # Track several errors
        for i in range(5):
            track_error(RuntimeError(f"Error {i}"))
        
        recent = error_tracker.get_recent_errors(limit=3)
        assert len(recent) == 3
        
        # Most recent should be first
        assert "Error 4" in recent[0]["message"]


@pytest.mark.asyncio
class TestResilienceIntegration:
    """Test combined retry + circuit breaker"""
    
    async def test_combined_resilience(self):
        """Test retry with circuit breaker"""
        call_count = 0
        
        @with_resilience(
            retry_config=RetryConfig(max_attempts=2, initial_delay=0.01),
            circuit_breaker_name="test_service"
        )
        async def resilient_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("Transient")
            return "success"
        
        result = await resilient_func()
        
        assert result == "success"
        assert call_count == 2
