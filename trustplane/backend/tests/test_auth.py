"""
Tests for authentication and tenant context
"""
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timedelta

from app.core.auth import SupabaseAuth, JWTPayload
from app.core.tenant import TenantContext, TenantContextManager
from app.core.exceptions import AuthenticationError, TenantIsolationError


class TestSupabaseAuth:
    """Tests for Supabase JWT authentication"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.auth = SupabaseAuth()
        self.valid_payload = {
            "sub": str(uuid4()),
            "email": "test@example.com",
            "org_id": str(uuid4()),
            "role": "admin",
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
            "iat": int(datetime.utcnow().timestamp()),
        }
    
    def test_decode_token_without_secret(self):
        """Should raise error when JWT secret not configured"""
        auth = SupabaseAuth()
        auth.jwt_secret = ""
        
        with pytest.raises(AuthenticationError) as exc:
            auth.decode_token("fake-token")
        
        assert "not configured" in str(exc.value)
    
    def test_validate_token_returns_false_for_invalid(self):
        """Should return False for invalid tokens"""
        auth = SupabaseAuth()
        auth.jwt_secret = "test-secret"
        
        result = auth.validate_token("invalid-token")
        assert result is False


class TestTenantContext:
    """Tests for tenant context"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.org_id = uuid4()
        self.user_id = uuid4()
        self.context = TenantContext(
            org_id=self.org_id,
            user_id=self.user_id,
            email="test@example.com",
            role="member",
            permissions=["workflow:read", "workflow:create"]
        )
    
    def test_has_permission_returns_true_for_existing(self):
        """Should return True when user has permission"""
        assert self.context.has_permission("workflow:read") is True
    
    def test_has_permission_returns_false_for_missing(self):
        """Should return False when user lacks permission"""
        assert self.context.has_permission("workflow:delete") is False
    
    def test_admin_has_all_permissions(self):
        """Admins should have all permissions"""
        admin_context = TenantContext(
            org_id=self.org_id,
            user_id=self.user_id,
            email="admin@example.com",
            role="admin",
            permissions=[]
        )
        assert admin_context.has_permission("anything") is True
    
    def test_validate_org_access_same_org(self):
        """Should not raise for same org access"""
        # Should not raise
        self.context.validate_org_access(self.org_id)
    
    def test_validate_org_access_different_org(self):
        """Should raise for different org access"""
        other_org = uuid4()
        
        with pytest.raises(TenantIsolationError):
            self.context.validate_org_access(other_org)
    
    def test_is_admin(self):
        """Should correctly identify admin role"""
        assert self.context.is_admin() is False
        
        admin = TenantContext(
            org_id=self.org_id,
            user_id=self.user_id,
            email="admin@example.com",
            role="admin",
        )
        assert admin.is_admin() is True
    
    def test_to_dict(self):
        """Should serialize to dict correctly"""
        result = self.context.to_dict()
        
        assert result["org_id"] == str(self.org_id)
        assert result["user_id"] == str(self.user_id)
        assert result["email"] == "test@example.com"
        assert result["role"] == "member"


class TestTenantContextManager:
    """Tests for tenant context manager"""
    
    def test_context_manager_sets_and_clears(self):
        """Should set context in with block and clear after"""
        from app.core.tenant import get_current_tenant, clear_current_tenant
        
        org_id = uuid4()
        context = TenantContext(
            org_id=org_id,
            user_id=uuid4(),
            email="test@example.com",
            role="member",
        )
        
        # Before - should be None
        clear_current_tenant()
        assert get_current_tenant() is None
        
        # During - should be set
        with TenantContextManager(context) as ctx:
            assert get_current_tenant() is not None
            assert get_current_tenant().org_id == org_id
        
        # After - should be cleared
        assert get_current_tenant() is None
