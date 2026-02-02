"""
Application configuration with environment variable support
"""
from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment"""
    
    # Application
    PROJECT_NAME: str = "TrustPlane"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # API
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""
    
    # Database
    DATABASE_URL: str = ""
    
    # AI / LLM
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4-turbo-preview"
    LLM_TEMPERATURE: float = 0.0  # Deterministic for production
    
    # Security
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # SLA Engine
    SLA_CHECK_INTERVAL_SECONDS: int = 60
    SLA_PREDICTION_HORIZON_HOURS: int = 24
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


settings = get_settings()
