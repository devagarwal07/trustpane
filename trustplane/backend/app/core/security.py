"""
Security utilities - JWT validation, hashing, encryption
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hashlib
import hmac
import secrets

from app.core.config import settings


def generate_hash(data: str) -> str:
    """Generate SHA-256 hash of data"""
    return hashlib.sha256(data.encode()).hexdigest()


def chain_hash(previous_hash: str, current_data: str) -> str:
    """Generate hash chained to previous hash for tamper detection"""
    combined = f"{previous_hash}:{current_data}"
    return generate_hash(combined)


def verify_hash_chain(events: list) -> bool:
    """Verify integrity of hash chain"""
    if not events:
        return True
    
    for i, event in enumerate(events):
        if i == 0:
            # First event should have genesis hash
            expected = generate_hash(f"genesis:{event['data']}")
        else:
            expected = chain_hash(events[i-1]['hash'], event['data'])
        
        if event['hash'] != expected:
            return False
    
    return True


def generate_idempotency_key() -> str:
    """Generate unique idempotency key"""
    return secrets.token_urlsafe(32)


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks"""
    return hmac.compare_digest(a.encode(), b.encode())
