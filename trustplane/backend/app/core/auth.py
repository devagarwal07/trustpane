"""
Supabase JWT Authentication
Validates JWTs and extracts tenant context for multi-tenant isolation
"""
from datetime import datetime
from typing import Optional, Dict, Any
from jose import jwt, JWTError, ExpiredSignatureError
from pydantic import BaseModel
import httpx

from app.core.config import settings
from app.core.exceptions import AuthenticationError


class JWTPayload(BaseModel):
    """Validated JWT payload structure"""
    sub: str  # User ID
    email: Optional[str] = None
    org_id: Optional[str] = None
    role: str = "member"
    aud: Optional[str] = None
    exp: int
    iat: int
    
    # Supabase specific claims
    app_metadata: Dict[str, Any] = {}
    user_metadata: Dict[str, Any] = {}


class SupabaseAuth:
    """
    Supabase JWT authentication handler.
    
    Validates tokens using Supabase JWT secret and extracts claims
    for tenant isolation and authorization.
    """
    
    def __init__(self):
        self.jwt_secret = settings.SUPABASE_JWT_SECRET
        self.algorithms = ["HS256"]
        self._jwks_cache: Optional[Dict] = None
        self._jwks_cache_time: Optional[datetime] = None
    
    def decode_token(self, token: str) -> JWTPayload:
        """
        Decode and validate a Supabase JWT token.
        
        Args:
            token: The JWT token string
            
        Returns:
            JWTPayload with validated claims
            
        Raises:
            AuthenticationError: If token is invalid or expired
        """
        if not self.jwt_secret:
            raise AuthenticationError("JWT secret not configured")
        
        try:
            # Decode the token
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=self.algorithms,
                options={
                    "verify_aud": False,  # Supabase doesn't always set audience
                    "verify_iss": False,  # We validate by secret
                }
            )
            
            # Extract org_id from app_metadata if not in root claims
            org_id = payload.get("org_id")
            if not org_id:
                app_metadata = payload.get("app_metadata", {})
                org_id = app_metadata.get("org_id")
            
            # Extract role from app_metadata if not in root claims
            role = payload.get("role")
            if not role:
                app_metadata = payload.get("app_metadata", {})
                role = app_metadata.get("role", "member")
            
            return JWTPayload(
                sub=payload.get("sub", ""),
                email=payload.get("email"),
                org_id=org_id,
                role=role,
                aud=payload.get("aud"),
                exp=payload.get("exp", 0),
                iat=payload.get("iat", 0),
                app_metadata=payload.get("app_metadata", {}),
                user_metadata=payload.get("user_metadata", {}),
            )
            
        except ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except JWTError as e:
            raise AuthenticationError(f"Invalid token: {str(e)}")
        except Exception as e:
            raise AuthenticationError(f"Token validation failed: {str(e)}")
    
    def validate_token(self, token: str) -> bool:
        """
        Quick validation check without full decode.
        
        Returns:
            True if token is valid, False otherwise
        """
        try:
            self.decode_token(token)
            return True
        except AuthenticationError:
            return False
    
    def get_user_id(self, token: str) -> str:
        """Extract user ID from token"""
        payload = self.decode_token(token)
        return payload.sub
    
    def get_org_id(self, token: str) -> Optional[str]:
        """Extract organization ID from token"""
        payload = self.decode_token(token)
        return payload.org_id
    
    def is_token_expired(self, token: str) -> bool:
        """Check if token is expired without raising"""
        try:
            payload = self.decode_token(token)
            return datetime.utcnow().timestamp() > payload.exp
        except AuthenticationError:
            return True


# Singleton instance
supabase_auth = SupabaseAuth()
