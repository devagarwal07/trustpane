"""
Tests for Security Middleware
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.security import (
    SecurityHeadersMiddleware,
    CORSSecurityMiddleware,
    RequestSizeLimitMiddleware,
    IPWhitelistMiddleware
)


class TestSecurityHeaders:
    """Test security headers middleware"""
    
    def setup_method(self):
        """Create test app"""
        self.app = FastAPI()
        self.app.add_middleware(SecurityHeadersMiddleware)
        
        @self.app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        self.client = TestClient(self.app)
    
    def test_security_headers_present(self):
        """Test all security headers are added"""
        response = self.client.get("/test")
        
        # Check all security headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in response.headers
        assert response.headers["X-Powered-By"] == "TrustPlane"
    
    def test_server_header_removed(self):
        """Test Server header is removed"""
        response = self.client.get("/test")
        
        # Server header should not reveal internal details
        assert response.headers.get("Server") != "uvicorn"
    
    def test_permissions_policy(self):
        """Test permissions policy disables sensitive features"""
        response = self.client.get("/test")
        
        permissions = response.headers["Permissions-Policy"]
        
        # Should disable dangerous features
        assert "camera=()" in permissions
        assert "microphone=()" in permissions
        assert "geolocation=()" in permissions
        assert "payment=()" in permissions


class TestCORSSecurity:
    """Test CORS security middleware"""
    
    def test_allowed_origin(self):
        """Test requests from allowed origins"""
        app = FastAPI()
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["https://app.trustplane.com"]
        )
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        response = client.get(
            "/test",
            headers={"Origin": "https://app.trustplane.com"}
        )
        
        assert response.headers["Access-Control-Allow-Origin"] == "https://app.trustplane.com"
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
    
    def test_disallowed_origin(self):
        """Test requests from disallowed origins are blocked"""
        app = FastAPI()
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["https://app.trustplane.com"]
        )
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        response = client.get(
            "/test",
            headers={"Origin": "https://evil.com"}
        )
        
        # Should not have CORS headers
        assert "Access-Control-Allow-Origin" not in response.headers
    
    def test_wildcard_subdomain(self):
        """Test wildcard subdomain matching"""
        app = FastAPI()
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["*.trustplane.com"]
        )
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Subdomain should be allowed
        response = client.get(
            "/test",
            headers={"Origin": "https://staging.trustplane.com"}
        )
        
        assert response.headers["Access-Control-Allow-Origin"] == "https://staging.trustplane.com"
    
    def test_preflight_request(self):
        """Test CORS preflight (OPTIONS) requests"""
        app = FastAPI()
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["https://app.trustplane.com"]
        )
        
        @app.post("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        response = client.options(
            "/test",
            headers={"Origin": "https://app.trustplane.com"}
        )
        
        assert response.status_code == 200
        assert "Access-Control-Allow-Methods" in response.headers
        assert "Access-Control-Allow-Headers" in response.headers
        assert "Access-Control-Max-Age" in response.headers
    
    def test_exposed_headers(self):
        """Test custom headers are exposed"""
        app = FastAPI()
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["https://app.trustplane.com"]
        )
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        response = client.get(
            "/test",
            headers={"Origin": "https://app.trustplane.com"}
        )
        
        exposed = response.headers["Access-Control-Expose-Headers"]
        
        # Should expose rate limit and error headers
        assert "X-RateLimit-Limit" in exposed
        assert "X-Error-ID" in exposed
        assert "X-Request-ID" in exposed


class TestRequestSizeLimit:
    """Test request size limiting"""
    
    def test_request_within_limit(self):
        """Test requests within size limit are allowed"""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size=1024)  # 1KB
        
        @app.post("/test")
        async def test_endpoint(data: dict):
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Small request should succeed
        response = client.post("/test", json={"data": "small"})
        assert response.status_code == 200
    
    def test_request_exceeds_limit(self):
        """Test requests exceeding size limit are rejected"""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_size=100)  # 100 bytes
        
        @app.post("/test")
        async def test_endpoint(data: dict):
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Large request should be rejected
        large_data = {"data": "x" * 1000}
        
        # Set content-length manually to trigger check
        response = client.post(
            "/test",
            json=large_data,
            headers={"Content-Length": "2000"}
        )
        
        assert response.status_code == 413
        error = response.json()
        assert error["error"]["code"] == "REQUEST_TOO_LARGE"


class TestIPWhitelist:
    """Test IP whitelisting"""
    
    def test_whitelisted_ip_allowed(self):
        """Test whitelisted IP can access protected paths"""
        app = FastAPI()
        app.add_middleware(
            IPWhitelistMiddleware,
            whitelisted_ips=["192.168.1.100"],
            protected_paths=["/admin"]
        )
        
        @app.get("/admin/stats")
        async def admin_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Mock X-Forwarded-For header
        response = client.get(
            "/admin/stats",
            headers={"X-Forwarded-For": "192.168.1.100"}
        )
        
        assert response.status_code == 200
    
    def test_non_whitelisted_ip_blocked(self):
        """Test non-whitelisted IP cannot access protected paths"""
        app = FastAPI()
        app.add_middleware(
            IPWhitelistMiddleware,
            whitelisted_ips=["192.168.1.100"],
            protected_paths=["/admin"]
        )
        
        @app.get("/admin/stats")
        async def admin_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Different IP
        response = client.get(
            "/admin/stats",
            headers={"X-Forwarded-For": "10.0.0.1"}
        )
        
        assert response.status_code == 403
        error = response.json()
        assert error["error"]["code"] == "FORBIDDEN"
    
    def test_unprotected_path_accessible(self):
        """Test unprotected paths are accessible to all"""
        app = FastAPI()
        app.add_middleware(
            IPWhitelistMiddleware,
            whitelisted_ips=["192.168.1.100"],
            protected_paths=["/admin"]
        )
        
        @app.get("/public/data")
        async def public_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        # Any IP should access public path
        response = client.get(
            "/public/data",
            headers={"X-Forwarded-For": "10.0.0.1"}
        )
        
        assert response.status_code == 200


class TestSecurityIntegration:
    """Test multiple security middleware together"""
    
    def test_layered_security(self):
        """Test multiple security layers work together"""
        app = FastAPI()
        
        # Add all security middleware
        app.add_middleware(SecurityHeadersMiddleware)
        app.add_middleware(RequestSizeLimitMiddleware, max_size=10000)
        app.add_middleware(
            CORSSecurityMiddleware,
            allowed_origins=["https://app.trustplane.com"]
        )
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        client = TestClient(app)
        
        response = client.get(
            "/test",
            headers={"Origin": "https://app.trustplane.com"}
        )
        
        # Should have both security and CORS headers
        assert "X-Content-Type-Options" in response.headers
        assert "Access-Control-Allow-Origin" in response.headers
        assert response.status_code == 200
