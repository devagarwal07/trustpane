"""
Tests for Rate Limiting
"""
import pytest
import asyncio
import time
from app.core.rate_limiting import (
    TokenBucket, SlidingWindow, FixedWindow,
    RateLimiter, RateLimitConfig, RateLimitStrategy
)
from app.core.exceptions import RateLimitExceededError


class TestTokenBucket:
    """Test token bucket algorithm"""
    
    def test_initial_capacity(self):
        """Test bucket starts at full capacity"""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        assert bucket.get_available_tokens() == 10
    
    def test_consume_tokens(self):
        """Test consuming tokens"""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        assert bucket.consume(5) is True
        assert bucket.get_available_tokens() == 5
        
        assert bucket.consume(5) is True
        assert bucket.get_available_tokens() == 0
        
        # Should fail - no tokens left
        assert bucket.consume(1) is False
    
    def test_refill_over_time(self):
        """Test tokens refill at specified rate"""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens per second
        
        # Consume all tokens
        bucket.consume(10)
        assert bucket.get_available_tokens() == 0
        
        # Wait for refill
        time.sleep(0.5)  # Should refill 5 tokens
        
        available = bucket.get_available_tokens()
        assert 4 <= available <= 6  # Allow for timing variance
    
    def test_wait_time_calculation(self):
        """Test wait time until tokens available"""
        bucket = TokenBucket(capacity=10, refill_rate=2.0)  # 2 tokens per second
        
        # Consume all tokens
        bucket.consume(10)
        
        # Need 1 token - should wait 0.5 seconds
        wait_time = bucket.get_wait_time(1)
        assert 0.4 <= wait_time <= 0.6


class TestSlidingWindow:
    """Test sliding window algorithm"""
    
    def test_allows_requests_within_limit(self):
        """Test requests allowed within limit"""
        window = SlidingWindow(max_requests=5, window_seconds=10)
        
        # Should allow 5 requests
        for _ in range(5):
            assert window.record_request() is True
        
        # 6th request should fail
        assert window.record_request() is False
    
    def test_window_cleanup(self):
        """Test old requests are removed from window"""
        window = SlidingWindow(max_requests=3, window_seconds=1)
        
        # Fill window
        for _ in range(3):
            assert window.record_request() is True
        
        # Should be blocked
        assert window.record_request() is False
        
        # Wait for window to expire
        time.sleep(1.1)
        
        # Should allow new requests
        assert window.record_request() is True
    
    def test_get_request_count(self):
        """Test getting current request count"""
        window = SlidingWindow(max_requests=5, window_seconds=10)
        
        for i in range(3):
            window.record_request()
            assert window.get_request_count() == i + 1


class TestFixedWindow:
    """Test fixed window algorithm"""
    
    def test_allows_requests_within_window(self):
        """Test requests allowed within fixed window"""
        window = FixedWindow(max_requests=5, window_seconds=10)
        
        # Should allow 5 requests
        for _ in range(5):
            assert window.record_request() is True
        
        # 6th request should fail
        assert window.record_request() is False
    
    def test_window_reset(self):
        """Test window resets after expiry"""
        window = FixedWindow(max_requests=3, window_seconds=1)
        
        # Fill window
        for _ in range(3):
            assert window.record_request() is True
        
        # Should be blocked
        assert window.record_request() is False
        
        # Wait for window reset
        time.sleep(1.1)
        
        # Should allow new requests
        assert window.record_request() is True
        assert window.get_request_count() == 1


class TestRateLimiter:
    """Test rate limiter with multiple strategies"""
    
    def setup_method(self):
        """Create fresh rate limiter for each test"""
        self.limiter = RateLimiter()
    
    def test_ip_rate_limit(self):
        """Test IP-based rate limiting"""
        config = RateLimitConfig(
            requests=3,
            window_seconds=60,
            strategy=RateLimitStrategy.TOKEN_BUCKET
        )
        self.limiter.configure_ip_rate_limit(config)
        
        # First 3 requests should succeed
        for _ in range(3):
            allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.1")
            assert allowed is True
        
        # 4th request should fail
        allowed, retry_after = self.limiter.check_rate_limit(ip="192.168.1.1")
        assert allowed is False
        assert retry_after is not None
    
    def test_user_rate_limit(self):
        """Test user-based rate limiting"""
        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            strategy=RateLimitStrategy.SLIDING_WINDOW
        )
        self.limiter.configure_user_rate_limit(config)
        
        # First 5 requests should succeed
        for _ in range(5):
            allowed, _ = self.limiter.check_rate_limit(user_id="user-123")
            assert allowed is True
        
        # 6th request should fail
        allowed, retry_after = self.limiter.check_rate_limit(user_id="user-123")
        assert allowed is False
    
    def test_endpoint_rate_limit(self):
        """Test endpoint-specific rate limiting"""
        config = RateLimitConfig(
            requests=2,
            window_seconds=60,
            strategy=RateLimitStrategy.FIXED_WINDOW
        )
        self.limiter.configure_endpoint_rate_limit("/api/auth/login", config)
        
        # First 2 requests should succeed
        for _ in range(2):
            allowed, _ = self.limiter.check_rate_limit(
                ip="192.168.1.1",
                endpoint="/api/auth/login"
            )
            assert allowed is True
        
        # 3rd request should fail
        allowed, retry_after = self.limiter.check_rate_limit(
            ip="192.168.1.1",
            endpoint="/api/auth/login"
        )
        assert allowed is False
    
    def test_independent_limiters(self):
        """Test different IPs/users have independent limits"""
        config = RateLimitConfig(requests=2, window_seconds=60)
        self.limiter.configure_ip_rate_limit(config)
        
        # IP 1 - consume limit
        for _ in range(2):
            allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.1")
            assert allowed is True
        
        # IP 1 - should be blocked
        allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.1")
        assert allowed is False
        
        # IP 2 - should still be allowed
        allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.2")
        assert allowed is True
    
    def test_get_rate_limit_info(self):
        """Test retrieving rate limit status"""
        config = RateLimitConfig(requests=10, window_seconds=60)
        self.limiter.configure_user_rate_limit(config)
        
        # Make some requests
        for _ in range(3):
            self.limiter.check_rate_limit(user_id="user-123")
        
        # Check status
        info = self.limiter.get_rate_limit_info(user_id="user-123")
        
        assert "user" in info
        assert info["user"]["limit"] == 10
        assert info["user"]["remaining"] <= 7  # At least 3 consumed
        assert info["user"]["reset_at"] > time.time()
    
    def test_reset_limiter(self):
        """Test resetting rate limiters"""
        config = RateLimitConfig(requests=2, window_seconds=60)
        self.limiter.configure_ip_rate_limit(config)
        
        # Consume limit
        for _ in range(2):
            self.limiter.check_rate_limit(ip="192.168.1.1")
        
        # Should be blocked
        allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.1")
        assert allowed is False
        
        # Reset limiter
        self.limiter.reset_limiter(ip="192.168.1.1")
        
        # Should be allowed again
        allowed, _ = self.limiter.check_rate_limit(ip="192.168.1.1")
        assert allowed is True


@pytest.mark.asyncio
class TestRateLimitMiddleware:
    """Test rate limit middleware integration"""
    
    async def test_rate_limit_headers_added(self):
        """Test rate limit headers are added to response"""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.middleware.rate_limit import RateLimitMiddleware
        from app.core.rate_limiting import rate_limiter, RateLimitConfig, RateLimitStrategy
        
        # Configure rate limiter
        rate_limiter.configure_ip_rate_limit(
            RateLimitConfig(requests=10, window_seconds=60, strategy=RateLimitStrategy.TOKEN_BUCKET)
        )
        
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        response = client.get("/test")
        
        # Check headers present
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
    
    async def test_rate_limit_exceeded_error(self):
        """Test rate limit exceeded returns 429"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.middleware.rate_limit import RateLimitMiddleware
        from app.core.rate_limiting import rate_limiter, RateLimitConfig, RateLimitStrategy
        
        # Reset limiter
        rate_limiter._ip_limiters.clear()
        
        # Configure very low limit
        rate_limiter.configure_ip_rate_limit(
            RateLimitConfig(requests=2, window_seconds=60, strategy=RateLimitStrategy.TOKEN_BUCKET)
        )
        
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)
        
        # Register exception handler
        from app.middleware.exception_handlers import trustplane_exception_handler
        from app.core.exceptions import TrustPlaneException
        app.add_exception_handler(TrustPlaneException, trustplane_exception_handler)
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # First 2 requests should succeed
        response1 = client.get("/test")
        assert response1.status_code == 200
        
        response2 = client.get("/test")
        assert response2.status_code == 200
        
        # 3rd request should fail with 429
        response3 = client.get("/test")
        assert response3.status_code == 429
        
        # Check error response
        error = response3.json()
        assert error["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry_after" in error["error"]["details"]


@pytest.mark.asyncio
class TestConcurrentRateLimiting:
    """Test rate limiting under concurrent load"""
    
    async def test_concurrent_token_bucket(self):
        """Test token bucket handles concurrent requests"""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        
        success_count = 0
        failure_count = 0
        
        async def make_request():
            nonlocal success_count, failure_count
            if bucket.consume(1):
                success_count += 1
            else:
                failure_count += 1
        
        # Fire 20 concurrent requests
        tasks = [make_request() for _ in range(20)]
        await asyncio.gather(*tasks)
        
        # Should allow exactly 10 (capacity)
        assert success_count == 10
        assert failure_count == 10
