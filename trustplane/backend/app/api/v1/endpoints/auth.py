"""
Authentication endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

router = APIRouter()


@router.get("/me")
async def get_current_user() -> Dict[str, Any]:
    """Get current authenticated user"""
    # Will be implemented with Supabase JWT validation
    return {"message": "Endpoint ready for implementation"}


@router.post("/refresh")
async def refresh_token() -> Dict[str, Any]:
    """Refresh authentication token"""
    return {"message": "Endpoint ready for implementation"}
