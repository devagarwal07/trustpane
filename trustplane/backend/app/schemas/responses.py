"""
Standard API response schemas
"""
from typing import Generic, TypeVar, Optional, List, Any
from pydantic import BaseModel
from datetime import datetime

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper"""
    success: bool
    data: Optional[T] = None
    message: Optional[str] = None
    timestamp: datetime = datetime.utcnow()


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper"""
    items: List[T]
    total: int
    page: int
    page_size: int
    has_more: bool


class ErrorResponse(BaseModel):
    """Error response schema"""
    success: bool = False
    error: str
    code: str
    details: Optional[dict] = None
    timestamp: datetime = datetime.utcnow()
    correlation_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime = datetime.utcnow()
