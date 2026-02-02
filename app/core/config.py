"""Configuration settings for Lead Machine."""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "Lead Machine"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_KEY: str = ""

    # Database
    DATABASE_URL: str = "sqlite:///./data/leadmachine.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # GoHighLevel
    GHL_API_KEY: str = ""
    GHL_LOCATION_ID: str = ""
    GHL_API_URL: str = "https://services.leadconnectorhq.com"

    # Scraper settings
    SCRAPER_MAX_PAGES: int = 20
    SCRAPER_RATE_LIMIT: float = 2.0  # requests per second per domain
    SCRAPER_TIMEOUT: int = 30

    # Verifier settings
    VERIFIER_SMTP_TIMEOUT: int = 10
    VERIFIER_MAX_CONCURRENT: int = 5
    VERIFIER_CACHE_DAYS: int = 7

    # Warmup settings
    WARMUP_CHECK_INTERVAL: int = 300  # 5 minutes
    WARMUP_REPLY_PROBABILITY: float = 0.7
    WARMUP_MIN_REPLY_DELAY: int = 300  # 5 minutes
    WARMUP_MAX_REPLY_DELAY: int = 1800  # 30 minutes

    # Encryption key for credentials
    ENCRYPTION_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
