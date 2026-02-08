"""
Retry Logic and Circuit Breaker Utilities

Provides decorators and utilities for handling transient failures
and protecting against cascading failures.
"""
import asyncio
import functools
import time
from typing import TypeVar, Callable, Any, Optional, Type, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from app.core.exceptions import TrustPlaneException, ServiceUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RetryConfig:
    """Configuration for retry logic"""
    max_attempts: int = 3
    initial_delay: float = 0.1  # seconds
    max_delay: float = 10.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Open circuit after N failures
    success_threshold: int = 2  # Close circuit after N successes
    timeout: float = 60.0  # Seconds before trying again
    expected_exception: Type[Exception] = Exception


class CircuitBreakerState:
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents cascading failures by stopping requests to failing services.
    """
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: str = CircuitBreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try again"""
        if self.last_failure_time is None:
            return True
        
        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.config.timeout
    
    def record_success(self):
        """Record successful operation"""
        self.failure_count = 0
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                logger.info(f"Circuit breaker '{self.name}' CLOSED (recovered)")
                self.state = CircuitBreakerState.CLOSED
                self.success_count = 0
    
    def record_failure(self, exception: Exception):
        """Record failed operation"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.state == CircuitBreakerState.HALF_OPEN:
            logger.warning(f"Circuit breaker '{self.name}' OPEN (failed recovery attempt)")
            self.state = CircuitBreakerState.OPEN
            self.success_count = 0
        
        elif self.failure_count >= self.config.failure_threshold:
            logger.error(
                f"Circuit breaker '{self.name}' OPEN "
                f"(threshold {self.config.failure_threshold} failures exceeded)"
            )
            self.state = CircuitBreakerState.OPEN
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection"""
        # Check if we should attempt
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                logger.info(f"Circuit breaker '{self.name}' HALF_OPEN (testing recovery)")
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
            else:
                raise ServiceUnavailableError(
                    f"Circuit breaker '{self.name}' is OPEN",
                    retry_after=int(self.config.timeout)
                )
        
        # Try to execute
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except self.config.expected_exception as e:
            self.record_failure(e)
            raise
    
    async def call_async(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute async function with circuit breaker protection"""
        # Check if we should attempt
        if self.state == CircuitBreakerState.OPEN:
            if self._should_attempt_reset():
                logger.info(f"Circuit breaker '{self.name}' HALF_OPEN (testing recovery)")
                self.state = CircuitBreakerState.HALF_OPEN
                self.success_count = 0
            else:
                raise ServiceUnavailableError(
                    f"Circuit breaker '{self.name}' is OPEN",
                    retry_after=int(self.config.timeout)
                )
        
        # Try to execute
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except self.config.expected_exception as e:
            self.record_failure(e)
            raise


# Global circuit breakers registry
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreaker:
    """Get or create a circuit breaker"""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(
            name=name,
            config=config or CircuitBreakerConfig()
        )
    return _circuit_breakers[name]


def with_retry(config: Optional[RetryConfig] = None):
    """
    Decorator to retry function on transient failures.
    
    Usage:
        @with_retry(RetryConfig(max_attempts=3))
        async def fetch_data():
            # ... potentially failing operation
            pass
    """
    retry_config = config or RetryConfig()
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception = None
            delay = retry_config.initial_delay
            
            for attempt in range(retry_config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except retry_config.retryable_exceptions as e:
                    last_exception = e
                    
                    # Check if exception is retryable
                    if isinstance(e, TrustPlaneException) and not e.retryable:
                        raise
                    
                    # Last attempt, don't wait
                    if attempt == retry_config.max_attempts - 1:
                        break
                    
                    # Calculate delay with exponential backoff
                    wait_time = min(delay, retry_config.max_delay)
                    
                    # Add jitter to prevent thundering herd
                    if retry_config.jitter:
                        import random
                        wait_time = wait_time * (0.5 + random.random())
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{retry_config.max_attempts} failed: {e}. "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    
                    await asyncio.sleep(wait_time)
                    delay *= retry_config.exponential_base
            
            # All attempts failed
            logger.error(
                f"All {retry_config.max_attempts} attempts failed. "
                f"Last error: {last_exception}"
            )
            raise last_exception
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None
            delay = retry_config.initial_delay
            
            for attempt in range(retry_config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except retry_config.retryable_exceptions as e:
                    last_exception = e
                    
                    # Check if exception is retryable
                    if isinstance(e, TrustPlaneException) and not e.retryable:
                        raise
                    
                    # Last attempt, don't wait
                    if attempt == retry_config.max_attempts - 1:
                        break
                    
                    # Calculate delay with exponential backoff
                    wait_time = min(delay, retry_config.max_delay)
                    
                    # Add jitter
                    if retry_config.jitter:
                        import random
                        wait_time = wait_time * (0.5 + random.random())
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{retry_config.max_attempts} failed: {e}. "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    
                    time.sleep(wait_time)
                    delay *= retry_config.exponential_base
            
            # All attempts failed
            logger.error(
                f"All {retry_config.max_attempts} attempts failed. "
                f"Last error: {last_exception}"
            )
            raise last_exception
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def with_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None
):
    """
    Decorator to protect function with circuit breaker.
    
    Usage:
        @with_circuit_breaker("openai_api")
        async def call_openai():
            # ... external API call
            pass
    """
    breaker = get_circuit_breaker(name, config)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            return await breaker.call_async(func, *args, **kwargs)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            return breaker.call(func, *args, **kwargs)
        
        # Return appropriate wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Combined decorator for common use case
def with_resilience(
    retry_config: Optional[RetryConfig] = None,
    circuit_breaker_name: Optional[str] = None,
    circuit_breaker_config: Optional[CircuitBreakerConfig] = None
):
    """
    Combined decorator for retry + circuit breaker.
    
    Usage:
        @with_resilience(
            retry_config=RetryConfig(max_attempts=3),
            circuit_breaker_name="supabase"
        )
        async def query_database():
            # ... database query
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # Apply decorators in order: circuit breaker (outer), then retry (inner)
        wrapped = func
        
        if retry_config:
            wrapped = with_retry(retry_config)(wrapped)
        
        if circuit_breaker_name:
            wrapped = with_circuit_breaker(
                circuit_breaker_name,
                circuit_breaker_config
            )(wrapped)
        
        return wrapped
    
    return decorator
