"""
API v1 Router - Aggregates all endpoint routers
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    organizations,
    workflows,
    sla,
    events,
    audit,
    agents,
    policies,
)

api_router = APIRouter()

# Authentication
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

# Organizations (tenants)
api_router.include_router(
    organizations.router,
    prefix="/organizations",
    tags=["Organizations"]
)

# Workflows
api_router.include_router(
    workflows.router,
    prefix="/workflows",
    tags=["Workflows"]
)

# SLA Management
api_router.include_router(
    sla.router,
    prefix="/sla",
    tags=["SLA"]
)

# Event Store
api_router.include_router(
    events.router,
    prefix="/events",
    tags=["Events"]
)

# Audit Logs
api_router.include_router(
    audit.router,
    prefix="/audit",
    tags=["Audit"]
)

# AI Agents
api_router.include_router(
    agents.router,
    prefix="/agents",
    tags=["AI Agents"]
)

# Policies
api_router.include_router(
    policies.router,
    prefix="/policies",
    tags=["Policies"]
)
