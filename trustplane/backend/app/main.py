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
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import (
    SecurityHeadersMiddleware,
    CORSSecurityMiddleware,
    RequestSizeLimitMiddleware,
)
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
    
    # Configure rate limiting
    logger.info("⏱️ Configuring rate limits...")
    from app.core.rate_limiting import configure_default_rate_limits, rate_limiter
    configure_default_rate_limits()
    await rate_limiter.start_cleanup_task()
    logger.info("✅ Rate limiting configured")
    
    # Initialize event handlers
    logger.info("📡 Registering event handlers...")
    from app.services.event_dispatcher import setup_default_handlers
    setup_default_handlers()
    logger.info("✅ Event handlers registered")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down TrustPlane")
    rate_limiter.stop_cleanup_task()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="""
## TrustPlane - Production SaaS Platform

Event-sourced, multi-tenant B2B SaaS platform for SLA management and enforcement with AI-powered agents.

### Key Features

- 🔐 **Enterprise Authentication** - JWT-based with Supabase integration
- 📊 **SLA Management** - Create, monitor, and enforce service level agreements
- 🤖 **AI Agents** - Automated task execution and ticket management
- 📈 **Real-time Analytics** - Comprehensive metrics and dashboards
- 🔔 **Multi-channel Notifications** - Email, Slack, webhooks
- 🌐 **WebSocket Support** - Live updates and real-time events
- 🔒 **Security Hardened** - Rate limiting, security headers, CORS
- 🚀 **Production Ready** - Error handling, monitoring, resilience patterns

### Architecture

- **Event Sourcing** - Append-only ledger with hash chaining for audit trail
- **Multi-tenancy** - Complete data isolation with RLS policies
- **Horizontal Scaling** - Stateless design with distributed rate limiting
- **Resilience** - Retry logic, circuit breakers, graceful degradation

### Support

- **Documentation**: https://docs.trustplane.com
- **Status**: https://status.trustplane.com
- **Support**: support@trustplane.com
    """,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
    contact={
        "name": "TrustPlane Support",
        "url": "https://trustplane.com/support",
        "email": "support@trustplane.com",
    },
    license_info={
        "name": "Commercial License",
        "url": "https://trustplane.com/license",
    },
    servers=[
        {
            "url": "https://api.trustplane.com",
            "description": "Production server"
        },
        {
            "url": "https://staging-api.trustplane.com",
            "description": "Staging server"
        },
        {
            "url": "http://localhost:8000",
            "description": "Development server"
        }
    ],
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "JWT authentication and user management"
        },
        {
            "name": "SLAs",
            "description": "Service Level Agreement management"
        },
        {
            "name": "Workflows",
            "description": "Workflow state machine and execution"
        },
        {
            "name": "Policies",
            "description": "Policy engine and rule evaluation"
        },
        {
            "name": "Tickets",
            "description": "Support ticket lifecycle management"
        },
        {
            "name": "Agents",
            "description": "AI agent orchestration and execution"
        },
        {
            "name": "Analytics",
            "description": "Metrics, dashboards, and reporting"
        },
        {
            "name": "Notifications",
            "description": "Multi-channel notification system"
        },
        {
            "name": "Events",
            "description": "Event sourcing and audit trail"
        },
        {
            "name": "Admin",
            "description": "Administrative operations"
        }
    ]
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

# Security headers - outermost layer
app.add_middleware(SecurityHeadersMiddleware)

# Request size limit - prevent DoS
app.add_middleware(RequestSizeLimitMiddleware, max_size=10 * 1024 * 1024)  # 10MB

# CORS with security checks
app.add_middleware(
    CORSSecurityMiddleware,
    allowed_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    max_age=600
)

# Rate limiting - throttle before authentication
app.add_middleware(RateLimitMiddleware)

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
