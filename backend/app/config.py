"""Application configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    """Aegis application settings.
    
    All variable names match the .env.example exactly.
    """
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://clearancerag:clearancerag@localhost:5432/clearancerag"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    
    # JWT
    JWT_SECRET_KEY: str = "change-me-to-a-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    
    # NextAuth
    NEXTAUTH_SECRET: str = ""
    NEXTAUTH_URL: str = "http://localhost:3000"
    
    # Backend
    BACKEND_URL: str = "http://localhost:8000"
    
    # CORS (comma-separated origins, e.g. "http://localhost:3000,https://myapp.com")
    CORS_ORIGINS: str = "http://localhost:3000"

    # Comma-separated IPs of trusted reverse proxies (nginx, load balancer).
    # X-Forwarded-For is only honored for the rate limiter when the direct
    # connection IP is in this set — otherwise any client could rotate the
    # header to bypass rate limiting. Empty by default (no proxy trusted).
    TRUSTED_PROXY_IPS: str = ""

    # How long (minutes) a Document may remain status="processing" with zero
    # associated chunks before the periodic cleanup task marks it "failed".
    STUCK_DOCUMENT_TIMEOUT_MINUTES: int = 60
    
    # Langfuse
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_production_secrets(self) -> 'Settings':
        if self.ENVIRONMENT == "production":
            if len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters in production to prevent "
                    "brute-force attacks against the HMAC-SHA256 signature."
                )
            if not self.OPENAI_API_KEY:
                raise ValueError(
                    "OPENAI_API_KEY must be set in production."
                )
        return self


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
