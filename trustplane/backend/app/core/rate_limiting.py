"""
Rate Limiting System
Implements token bucket and sliding window algorithms for API throttling
"""
import time
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timedelta
import asyncio
from enum import Enum

from app.core.exceptions import RateLimitExceededError


class RateLimitStrategy(str, Enum):
    """Rate limiting strategies"""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    requests: int  # Number of requests allowed
    window_seconds: int  # Time window in seconds
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    burst_size: Optional[int] = None  # Max burst (defaults to requests)
    
    def __post_init__(self):
        if self.burst_size is None:
            self.burst_size = self.requests


@dataclass
class TokenBucket:
    """Token bucket for rate limiting"""
    capacity: int
    refill_rate: float  # Tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    
    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.time()
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on refill rate
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens
        Returns True if successful, False if insufficient tokens
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def get_available_tokens(self) -> int:
        """Get current available tokens"""
        self._refill()
        return int(self.tokens)
    
    def get_wait_time(self, tokens: int = 1) -> float:
        """Get seconds to wait until tokens available"""
        self._refill()
        
        if self.tokens >= tokens:
            return 0.0
        
        needed = tokens - self.tokens
        return needed / self.refill_rate


@dataclass
class SlidingWindow:
    """Sliding window for rate limiting"""
    max_requests: int
    window_seconds: int
    requests: deque = field(default_factory=deque)
    
    def _cleanup_old_requests(self) -> None:
        """Remove requests outside the window"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()
    
    def is_allowed(self) -> bool:
        """Check if request is allowed"""
        self._cleanup_old_requests()
        return len(self.requests) < self.max_requests
    
    def record_request(self) -> bool:
        """
        Record a request
        Returns True if allowed, False if rate limit exceeded
        """
        self._cleanup_old_requests()
        
        if len(self.requests) >= self.max_requests:
            return False
        
        self.requests.append(time.time())
        return True
    
    def get_request_count(self) -> int:
        """Get current request count in window"""
        self._cleanup_old_requests()
        return len(self.requests)
    
    def get_wait_time(self) -> float:
        """Get seconds to wait until request allowed"""
        self._cleanup_old_requests()
        
        if len(self.requests) < self.max_requests:
            return 0.0
        
        # Wait until oldest request expires
        oldest = self.requests[0]
        now = time.time()
        wait_time = (oldest + self.window_seconds) - now
        return max(0.0, wait_time)


@dataclass
class FixedWindow:
    """Fixed window for rate limiting"""
    max_requests: int
    window_seconds: int
    request_count: int = 0
    window_start: float = field(default_factory=time.time)
    
    def _reset_if_needed(self) -> None:
        """Reset window if expired"""
        now = time.time()
        if now - self.window_start >= self.window_seconds:
            self.request_count = 0
            self.window_start = now
    
    def is_allowed(self) -> bool:
        """Check if request is allowed"""
        self._reset_if_needed()
        return self.request_count < self.max_requests
    
    def record_request(self) -> bool:
        """
        Record a request
        Returns True if allowed, False if rate limit exceeded
        """
        self._reset_if_needed()
        
        if self.request_count >= self.max_requests:
            return False
        
        self.request_count += 1
        return True
    
    def get_request_count(self) -> int:
        """Get current request count in window"""
        self._reset_if_needed()
        return self.request_count
    
    def get_wait_time(self) -> float:
        """Get seconds to wait until window resets"""
        self._reset_if_needed()
        
        if self.request_count < self.max_requests:
            return 0.0
        
        now = time.time()
        wait_time = (self.window_start + self.window_seconds) - now
        return max(0.0, wait_time)


class RateLimiter:
    """
    Multi-strategy rate limiter
    Supports per-IP, per-user, and per-endpoint rate limiting
    """
    
    def __init__(self):
        # Storage for different rate limit types
        self._ip_limiters: Dict[str, TokenBucket | SlidingWindow | FixedWindow] = {}
        self._user_limiters: Dict[str, TokenBucket | SlidingWindow | FixedWindow] = {}
        self._endpoint_limiters: Dict[str, TokenBucket | SlidingWindow | FixedWindow] = {}
        self._composite_limiters: Dict[str, TokenBucket | SlidingWindow | FixedWindow] = {}
        
        # Configurations
        self._ip_config: Optional[RateLimitConfig] = None
        self._user_config: Optional[RateLimitConfig] = None
        self._endpoint_configs: Dict[str, RateLimitConfig] = {}
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def configure_ip_rate_limit(self, config: RateLimitConfig) -> None:
        """Configure IP-based rate limiting"""
        self._ip_config = config
    
    def configure_user_rate_limit(self, config: RateLimitConfig) -> None:
        """Configure user-based rate limiting"""
        self._user_config = config
    
    def configure_endpoint_rate_limit(self, endpoint: str, config: RateLimitConfig) -> None:
        """Configure endpoint-specific rate limiting"""
        self._endpoint_configs[endpoint] = config
    
    def _create_limiter(self, config: RateLimitConfig):
        """Create limiter based on strategy"""
        if config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            refill_rate = config.requests / config.window_seconds
            return TokenBucket(
                capacity=config.burst_size or config.requests,
                refill_rate=refill_rate
            )
        elif config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            return SlidingWindow(
                max_requests=config.requests,
                window_seconds=config.window_seconds
            )
        else:  # FIXED_WINDOW
            return FixedWindow(
                max_requests=config.requests,
                window_seconds=config.window_seconds
            )
    
    def _get_or_create_limiter(
        self,
        storage: Dict,
        key: str,
        config: RateLimitConfig
    ):
        """Get existing limiter or create new one"""
        if key not in storage:
            storage[key] = self._create_limiter(config)
        return storage[key]
    
    def check_rate_limit(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> Tuple[bool, Optional[float]]:
        """
        Check if request is allowed
        Returns (allowed, retry_after_seconds)
        """
        max_wait_time = 0.0
        
        # Check IP rate limit
        if ip and self._ip_config:
            limiter = self._get_or_create_limiter(
                self._ip_limiters, ip, self._ip_config
            )
            if not self._check_limiter(limiter):
                wait_time = self._get_wait_time(limiter)
                max_wait_time = max(max_wait_time, wait_time)
                return False, max_wait_time
        
        # Check user rate limit
        if user_id and self._user_config:
            limiter = self._get_or_create_limiter(
                self._user_limiters, user_id, self._user_config
            )
            if not self._check_limiter(limiter):
                wait_time = self._get_wait_time(limiter)
                max_wait_time = max(max_wait_time, wait_time)
                return False, max_wait_time
        
        # Check endpoint rate limit
        if endpoint and endpoint in self._endpoint_configs:
            # Composite key for endpoint + IP/user
            composite_key = f"{endpoint}:{user_id or ip}"
            limiter = self._get_or_create_limiter(
                self._composite_limiters,
                composite_key,
                self._endpoint_configs[endpoint]
            )
            if not self._check_limiter(limiter):
                wait_time = self._get_wait_time(limiter)
                max_wait_time = max(max_wait_time, wait_time)
                return False, max_wait_time
        
        return True, None
    
    def _check_limiter(self, limiter) -> bool:
        """Check if limiter allows request"""
        if isinstance(limiter, TokenBucket):
            return limiter.consume(1)
        else:
            return limiter.record_request()
    
    def _get_wait_time(self, limiter) -> float:
        """Get wait time from limiter"""
        if isinstance(limiter, TokenBucket):
            return limiter.get_wait_time(1)
        else:
            return limiter.get_wait_time()
    
    def record_request(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> None:
        """
        Record a request (already checked)
        Note: For token bucket, consumption happens in check_rate_limit
        """
        pass  # Token bucket already consumed in check_rate_limit
    
    def get_rate_limit_info(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> Dict[str, any]:
        """Get current rate limit status"""
        info = {}
        
        # IP rate limit info
        if ip and self._ip_config and ip in self._ip_limiters:
            limiter = self._ip_limiters[ip]
            info["ip"] = {
                "limit": self._ip_config.requests,
                "window_seconds": self._ip_config.window_seconds,
                "remaining": self._get_remaining(limiter, self._ip_config),
                "reset_at": self._get_reset_time(limiter, self._ip_config)
            }
        
        # User rate limit info
        if user_id and self._user_config and user_id in self._user_limiters:
            limiter = self._user_limiters[user_id]
            info["user"] = {
                "limit": self._user_config.requests,
                "window_seconds": self._user_config.window_seconds,
                "remaining": self._get_remaining(limiter, self._user_config),
                "reset_at": self._get_reset_time(limiter, self._user_config)
            }
        
        return info
    
    def _get_remaining(self, limiter, config: RateLimitConfig) -> int:
        """Get remaining requests"""
        if isinstance(limiter, TokenBucket):
            return limiter.get_available_tokens()
        elif isinstance(limiter, (SlidingWindow, FixedWindow)):
            return config.requests - limiter.get_request_count()
        return 0
    
    def _get_reset_time(self, limiter, config: RateLimitConfig) -> float:
        """Get timestamp when rate limit resets"""
        now = time.time()
        
        if isinstance(limiter, TokenBucket):
            # Calculate when bucket will be full
            if limiter.tokens >= config.requests:
                return now
            needed = config.requests - limiter.tokens
            seconds = needed / limiter.refill_rate
            return now + seconds
        elif isinstance(limiter, FixedWindow):
            return limiter.window_start + config.window_seconds
        else:  # SlidingWindow
            if limiter.requests:
                return limiter.requests[0] + config.window_seconds
            return now
    
    async def start_cleanup_task(self, interval_seconds: int = 300):
        """Start background cleanup of expired limiters"""
        async def cleanup():
            while True:
                await asyncio.sleep(interval_seconds)
                self._cleanup_expired_limiters()
        
        self._cleanup_task = asyncio.create_task(cleanup())
    
    def _cleanup_expired_limiters(self):
        """Remove expired limiters to free memory"""
        now = time.time()
        
        # Cleanup IP limiters
        if self._ip_config:
            expired = [
                ip for ip, limiter in self._ip_limiters.items()
                if self._is_expired(limiter, self._ip_config, now)
            ]
            for ip in expired:
                del self._ip_limiters[ip]
        
        # Cleanup user limiters
        if self._user_config:
            expired = [
                user_id for user_id, limiter in self._user_limiters.items()
                if self._is_expired(limiter, self._user_config, now)
            ]
            for user_id in expired:
                del self._user_limiters[user_id]
        
        # Cleanup composite limiters
        for endpoint, config in self._endpoint_configs.items():
            expired = [
                key for key, limiter in self._composite_limiters.items()
                if key.startswith(f"{endpoint}:") and self._is_expired(limiter, config, now)
            ]
            for key in expired:
                del self._composite_limiters[key]
    
    def _is_expired(self, limiter, config: RateLimitConfig, now: float) -> bool:
        """Check if limiter is expired and can be cleaned up"""
        if isinstance(limiter, TokenBucket):
            # Consider expired if at full capacity and not used recently
            return (limiter.tokens >= config.requests and 
                    now - limiter.last_refill > config.window_seconds * 2)
        elif isinstance(limiter, FixedWindow):
            return now - limiter.window_start > config.window_seconds * 2
        else:  # SlidingWindow
            return len(limiter.requests) == 0 and now - limiter.requests[-1] > config.window_seconds * 2 if limiter.requests else True
    
    def stop_cleanup_task(self):
        """Stop background cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
    
    def reset_limiter(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> None:
        """Reset specific rate limiters (for testing or admin override)"""
        if ip and ip in self._ip_limiters:
            del self._ip_limiters[ip]
        
        if user_id and user_id in self._user_limiters:
            del self._user_limiters[user_id]
        
        if endpoint:
            # Remove all composite limiters for endpoint
            keys_to_remove = [
                key for key in self._composite_limiters.keys()
                if key.startswith(f"{endpoint}:")
            ]
            for key in keys_to_remove:
                del self._composite_limiters[key]


# Global rate limiter instance
rate_limiter = RateLimiter()


# Default configurations
DEFAULT_IP_RATE_LIMIT = RateLimitConfig(
    requests=100,  # 100 requests
    window_seconds=60,  # per minute
    strategy=RateLimitStrategy.TOKEN_BUCKET
)

DEFAULT_USER_RATE_LIMIT = RateLimitConfig(
    requests=1000,  # 1000 requests
    window_seconds=3600,  # per hour
    strategy=RateLimitStrategy.SLIDING_WINDOW
)

# Endpoint-specific limits
ENDPOINT_RATE_LIMITS = {
    "/api/auth/login": RateLimitConfig(
        requests=5,
        window_seconds=300,  # 5 attempts per 5 minutes
        strategy=RateLimitStrategy.FIXED_WINDOW
    ),
    "/api/auth/register": RateLimitConfig(
        requests=3,
        window_seconds=3600,  # 3 registrations per hour
        strategy=RateLimitStrategy.FIXED_WINDOW
    ),
    "/api/workflows": RateLimitConfig(
        requests=50,
        window_seconds=60,  # 50 per minute
        strategy=RateLimitStrategy.TOKEN_BUCKET,
        burst_size=100
    ),
}


def configure_default_rate_limits():
    """Configure default rate limits"""
    rate_limiter.configure_ip_rate_limit(DEFAULT_IP_RATE_LIMIT)
    rate_limiter.configure_user_rate_limit(DEFAULT_USER_RATE_LIMIT)
    
    for endpoint, config in ENDPOINT_RATE_LIMITS.items():
        rate_limiter.configure_endpoint_rate_limit(endpoint, config)
