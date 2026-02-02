"""
TrustPlane - Production SaaS Backend
Event-sourced, multi-tenant, AI-powered SLA enforcement platform
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    TrustPlaneException,
    AuthenticationError,
    TenantIsolationError,
)
from app.middleware.auth import AuthenticationMiddleware, TenantIsolationMiddleware
from app.middleware.exception_handlers import (
    trustplane_exception_handler,
    authentication_error_handler,
    tenant_isolation_error_handler,
    validation_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info(f"🚀 Starting TrustPlane v{settings.VERSION}")
    logger.info(f"Environment: {'DEBUG' if settings.DEBUG else 'PRODUCTION'}")
    
    # Initialize event handlers
    logger.info("📡 Registering event handlers...")
    from app.services.event_dispatcher import setup_default_handlers
    setup_default_handlers()
    logger.info("✅ Event handlers registered")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down TrustPlane")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Event-sourced SLA enforcement platform with AI agents",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs" if settings.DEBUG else None,  # Disable docs in production
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# =====================================================
# EXCEPTION HANDLERS
# Order matters - more specific handlers first
# =====================================================

app.add_exception_handler(AuthenticationError, authentication_error_handler)
app.add_exception_handler(TenantIsolationError, tenant_isolation_error_handler)
app.add_exception_handler(TrustPlaneException, trustplane_exception_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# =====================================================
# MIDDLEWARE
# Order matters - first added = outermost (runs first on request, last on response)
# =====================================================

# CORS - must be first
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],  # Expose request ID to frontend
)

# Authentication middleware - handles request ID and cleanup
app.add_middleware(AuthenticationMiddleware)

# Tenant isolation middleware - logs suspicious requests
app.add_middleware(TenantIsolationMiddleware)

# =====================================================
# ROUTES
# =====================================================

# Mount API v1 router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """
    Health check endpoint.
    Used by load balancers and monitoring systems.
    No authentication required.
    """
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "service": "trustplane-api"
    }


@app.get("/")
async def root():
    """Root endpoint - API info"""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_PREFIX}/docs" if settings.DEBUG else None,
        "health": "/health"
    }
