"""Application configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """ClearanceRAG application settings.
    
    All variable names match the .env.example exactly.
    """
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
    
    # Langfuse
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
