"""
API schemas for request/response models

This module defines Pydantic models for API contracts,
separate from domain models.
"""
from typing import TypeVar, Generic, Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID

T = TypeVar('T')


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper"""
    success: bool = True
    data: Optional[T] = None
    message: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response"""
    items: List[T]
    total: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =========================================================
# Event Schemas
# =========================================================

class EventResponse(BaseModel):
    """Event in API responses"""
    id: UUID
    stream_id: UUID
    event_type: str
    version: int
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    hash: str
    previous_hash: str
    actor_id: Optional[UUID]
    actor_type: str
    occurred_at: datetime
    recorded_at: datetime


class EventStreamResponse(BaseModel):
    """Event stream response"""
    stream_id: UUID
    events: List[EventResponse]
    event_count: int
    first_version: Optional[int]
    last_version: Optional[int]


class IntegrityReportResponse(BaseModel):
    """Integrity verification report"""
    valid: bool
    event_count: int
    broken_at: Optional[int] = None
    error: Optional[str] = None
    first_hash: Optional[str] = None
    last_hash: Optional[str] = None
    message: Optional[str] = None
    verified_at: datetime


class IntegrityCertificateResponse(BaseModel):
    """Integrity certificate for compliance"""
    stream_id: str
    event_count: int
    first_event_hash: Optional[str]
    last_event_hash: Optional[str]
    first_event_at: Optional[str]
    last_event_at: Optional[str]
    generated_at: str
    verification_status: str
    signature: str


class TimelineEntry(BaseModel):
    """Timeline entry for audit visualization"""
    version: int
    event_type: str
    occurred_at: str
    actor_type: str
    actor_id: Optional[str]
    summary: str
    hash_prefix: str

