"""
TrustPlane - Production SaaS Backend
Event-sourced, multi-tenant, AI-powered SLA enforcement platform
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    print(f"🚀 Starting TrustPlane v{settings.VERSION}")
    yield
    # Shutdown
    print("👋 Shutting down TrustPlane")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Event-sourced SLA enforcement platform with AI agents",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": settings.VERSION}
